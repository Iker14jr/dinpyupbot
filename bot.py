import asyncio
import json
import logging
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import imageio_ffmpeg
from dotenv import load_dotenv
from telegram import BotCommand, MenuButtonCommands, Update
from telegram.constants import ChatAction
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)
from telegram.request import HTTPXRequest
from yt_dlp import YoutubeDL


BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env", override=True)

DOWNLOADS_DIR = BASE_DIR / "downloads"
MAX_FILE_MB = int(os.getenv("MAX_FILE_MB", "48"))
MAX_FILE_BYTES = MAX_FILE_MB * 1024 * 1024
UPLOAD_TIMEOUT_SECONDS = float(os.getenv("UPLOAD_TIMEOUT_SECONDS", "900"))
SHORT_MAX_DURATION_SECONDS = int(os.getenv("SHORT_MAX_DURATION_SECONDS", "180"))
FFMPEG_PATH = imageio_ffmpeg.get_ffmpeg_exe()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger("dinpyupbot")

def _user_label(update: Update) -> str:
    user = update.effective_user
    if not user:
        return "desconocido"
    name = (user.full_name or user.username or "sin_nombre").replace("|", "/")
    uname = f"@{user.username}" if user.username else "sin_username"
    return f"{name} ({uname}) id={user.id}"


def log_download(update: Update, url: str, files: list, sent: int) -> None:
    from datetime import datetime
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    user = _user_label(update)
    files_str = ", ".join(files[:5])
    if len(files) > 5:
        files_str += f" (+{len(files)-5} mas)"
    line = f"{ts} | {user} | archivos={sent} | {files_str} | {url}\n"
    try:
        with open(BASE_DIR / "downloads.log", "a", encoding="utf-8") as f:
            f.write(line)
    except Exception:
        pass


def log_error(update: Update, url: str, error: str) -> None:
    from datetime import datetime
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    user = _user_label(update)
    err = str(error).replace("\n", " ")[:300]
    line = f"{ts} | {user} | {err} | {url}\n"
    try:
        with open(BASE_DIR / "errors.log", "a", encoding="utf-8") as f:
            f.write(line)
    except Exception:
        pass




@dataclass(frozen=True)
class DownloadResult:
    outputs: list[Path]
    work_dir: Path
    skipped_shorts: int = 0
    total_playlist_entries: int = 0


class AllPlaylistItemsAreShortsError(ValueError):
    pass



USERS_FILE = BASE_DIR / "users.json"


def _load_users() -> dict:
    if not USERS_FILE.exists():
        return {}
    try:
        return json.loads(USERS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_users(data: dict) -> None:
    try:
        USERS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def track_user(update: Update, message_id: int | None = None) -> None:
    user = update.effective_user
    chat = update.effective_chat
    if not user or not chat:
        return
    data = _load_users()
    key = str(user.id)
    entry = data.get(key, {})
    entry.update({
        "id": user.id,
        "chat_id": chat.id,
        "username": user.username or "",
        "full_name": user.full_name or "",
        "last_seen": __import__("datetime").datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    })
    if not entry.get("first_seen"):
        entry["first_seen"] = entry["last_seen"]
    msgs = entry.get("message_ids", [])
    if message_id:
        msgs.append(message_id)
        # keep last 40 message ids for cleanup
        msgs = msgs[-40:]
    entry["message_ids"] = msgs
    data[key] = entry
    _save_users(data)


def clear_user_chat(user_id: int) -> None:
    data = _load_users()
    key = str(user_id)
    if key in data:
        data[key]["message_ids"] = []
        data[key]["cleared_at"] = __import__("datetime").datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        _save_users(data)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.clear()
    msg = await update.effective_message.reply_text(
        "YouTube activo. Pásame un vídeo o una lista de reproducción y te lo devuelvo en MP3. Shorts no.",
    )
    track_user(update, msg.message_id if msg else None)
    if update.effective_message:
        track_user(update, update.effective_message.message_id)


async def restart(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await start(update, context)


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.clear()
    await update.effective_message.reply_text("Operación cancelada. Usa /restart para empezar otra vez.")


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (update.effective_message.text or "").strip()
    await process_urls(update, context, [text])


async def process_urls(update: Update, context: ContextTypes.DEFAULT_TYPE, urls: list[str]) -> None:
    if not urls:
        await update.effective_message.reply_text("Mándame al menos un enlace válido de YouTube.")
        return

    for index, text in enumerate(urls, start=1):
        prefix = f"[{index}/{len(urls)}] " if len(urls) > 1 else ""
        await process_url(update, context, text, prefix)


async def process_url(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str, prefix: str = "") -> None:
    if update.effective_message:
        track_user(update, update.effective_message.message_id)
    if not is_youtube_link(text):
        await update.effective_message.reply_text(f"{prefix}Mándame un enlace válido de YouTube.")
        return

    if is_youtube_short(text):
        await update.effective_message.reply_text(f"{prefix}Shorts no. Pásame un vídeo normal o una lista de reproducción.")
        return

    is_playlist = is_playlist_link(text)

    # Para vídeos individuales: comprobar también por metadatos (duración + vertical)
    if not is_playlist:
        try:
            with YoutubeDL(metadata_options()) as ydl:
                info = ydl.extract_info(text, download=False)
            if is_short_info(info):
                await update.effective_message.reply_text(f"{prefix}Shorts no. Pásame un vídeo normal o una lista de reproducción.")
                return
        except Exception:
            pass  # si falla la comprobación, seguimos e intentamos descargar

    status = await update.effective_message.reply_text(
        f"{prefix}Lista detectada. Revisando Shorts antes de descargar."
        if is_playlist
        else f"{prefix}Vídeo detectado. Descargando y convirtiendo a MP3."
    )
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.UPLOAD_DOCUMENT)

    result: DownloadResult | None = None
    try:
        result = await asyncio.to_thread(download_media, text, is_playlist)
        outputs = result.outputs
        if not outputs:
            await status.edit_text("No se generó ningún archivo descargable.")
            return

        if result.skipped_shorts:
            await status.edit_text(
                f"{prefix}Descarga lista. Enviando {len(outputs)} archivo(s). "
                f"Omitidos {result.skipped_shorts} Shorts."
            )
        else:
            await status.edit_text(f"{prefix}Descarga lista. Enviando {len(outputs)} archivo(s).")

        sent = 0
        skipped = 0
        for index, output in enumerate(outputs, start=1):
            size = output.stat().st_size
            if size > MAX_FILE_BYTES:
                skipped += 1
                continue

            await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.UPLOAD_DOCUMENT)
            with output.open("rb") as document:
                await context.bot.send_document(
                    chat_id=update.effective_chat.id,
                    document=document,
                    filename=output.name,
                    caption=f"Archivo {index}/{len(outputs)}",
                )
            sent += 1

        file_names = [o.name for o in outputs]
        log_download(update, text, file_names, sent)

        if skipped and result.skipped_shorts:
            await status.edit_text(
                f"{prefix}Listo. Enviados {sent}; omitidos {result.skipped_shorts} Shorts "
                f"y {skipped} por superar {MAX_FILE_MB} MB."
            )
        elif skipped:
            await status.edit_text(f"{prefix}Listo. Enviados {sent}; omitidos {skipped} por superar {MAX_FILE_MB} MB.")
        elif result.skipped_shorts:
            await status.edit_text(f"{prefix}Listo. Enviados {sent}; omitidos {result.skipped_shorts} Shorts.")
        else:
            await status.delete()
    except AllPlaylistItemsAreShortsError:
        log_error(update, text, "Toda la lista es de Shorts")
        await status.edit_text(f"{prefix}Toda la lista de reproducción es de Shorts y no puedo descargarla. Prueba con otra.")
    except Exception as exc:
        logger.exception("Download failed")
        log_error(update, text, str(exc))
        await status.edit_text(f"{prefix}No he podido procesarlo: {exc}")
    finally:
        if result:
            shutil.rmtree(result.work_dir, ignore_errors=True)
        context.user_data.clear()


def is_youtube_link(url: str) -> bool:
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    if parsed.scheme not in {"http", "https"}:
        return False
    return any(domain in host for domain in ("youtube.com", "youtu.be"))


def is_youtube_short(url: str) -> bool:
    parsed = urlparse(url)
    return "/shorts/" in parsed.path.lower()


def is_playlist_link(url: str) -> bool:
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    return bool(query.get("list"))


def download_media(url: str, is_playlist: bool) -> DownloadResult:
    DOWNLOADS_DIR.mkdir(exist_ok=True)
    work_dir = Path(tempfile.mkdtemp(prefix="job-", dir=DOWNLOADS_DIR))
    try:
        outputs, skipped_shorts, total_playlist_entries = download_youtube(url, work_dir, is_playlist)
        return DownloadResult(outputs, work_dir, skipped_shorts, total_playlist_entries)
    except Exception:
        shutil.rmtree(work_dir, ignore_errors=True)
        raise


def download_youtube(url: str, work_dir: Path, is_playlist: bool) -> tuple[list[Path], int, int]:
    if is_playlist:
        download_urls, skipped_shorts, total_playlist_entries = playlist_download_urls(url)
        output_template = str(work_dir / "%(autonumber)03d - %(title).120s.%(ext)s")
    else:
        download_urls = [url]
        skipped_shorts = 0
        total_playlist_entries = 0
        output_template = str(work_dir / "%(title).120s.%(ext)s")

    options = {
        "outtmpl": output_template,
        "noplaylist": True,
        "ffmpeg_location": FFMPEG_PATH,
        "quiet": True,
        "noprogress": True,
        "no_warnings": True,
        "ignoreerrors": is_playlist,
        "format": "bestaudio/best/best",
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }
        ],
        # Mitigar 403 de YouTube
        "extractor_args": {
            "youtube": {
                "player_client": ["android", "ios", "mweb", "web"],
            }
        },
        "http_headers": {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        },
    }

    with YoutubeDL(options) as ydl:
        ydl.download(download_urls)

    return collected_files(work_dir, "mp3"), skipped_shorts, total_playlist_entries


def playlist_download_urls(url: str) -> tuple[list[str], int, int]:
    with YoutubeDL(metadata_options(extract_flat=True)) as ydl:
        playlist_info = ydl.extract_info(url, download=False)

    entries = [entry for entry in playlist_info.get("entries", []) if entry]
    if not entries:
        raise FileNotFoundError("La lista de reproducción no tiene vídeos disponibles")

    download_urls: list[str] = []
    skipped_shorts = 0
    for entry in entries:
        entry_url = entry_to_url(entry)
        if is_short_info(entry):
            skipped_shorts += 1
            continue

        with YoutubeDL(metadata_options()) as ydl:
            full_info = ydl.extract_info(entry_url, download=False)

        if is_short_info(full_info):
            skipped_shorts += 1
            continue

        download_urls.append(full_info.get("webpage_url") or entry_url)

    if not download_urls:
        raise AllPlaylistItemsAreShortsError()

    return download_urls, skipped_shorts, len(entries)


def metadata_options(extract_flat: bool = False) -> dict:
    options = {
        "quiet": True,
        "noprogress": True,
        "no_warnings": True,
        "skip_download": True,
        "noplaylist": not extract_flat,
        "extract_flat": extract_flat,
        "ignoreerrors": extract_flat,
        "extractor_args": {
            "youtube": {
                "player_client": ["android", "ios", "mweb", "web"],
            }
        },
        "http_headers": {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        },
    }
    return options


def entry_to_url(entry: dict) -> str:
    for key in ("webpage_url", "original_url", "url"):
        value = entry.get(key)
        if isinstance(value, str) and value.startswith(("http://", "https://")):
            return value

    video_id = entry.get("id") or entry.get("url")
    if not video_id:
        raise ValueError("No he podido leer un vídeo de la lista de reproducción")
    return f"https://www.youtube.com/watch?v={video_id}"


def is_short_info(info: dict) -> bool:
    url_values = [
        info.get("webpage_url"),
        info.get("original_url"),
        info.get("url"),
        info.get("display_id"),
    ]
    if any(isinstance(value, str) and is_youtube_short(value) for value in url_values):
        return True

    duration = info.get("duration")
    width = info.get("width")
    height = info.get("height")
    if not isinstance(duration, (int, float)) or duration > SHORT_MAX_DURATION_SECONDS:
        return False
    if not isinstance(width, int) or not isinstance(height, int):
        return False
    return height > width


def collected_files(directory: Path, extension: str) -> list[Path]:
    matches = [path for path in directory.rglob(f"*.{extension}") if path.is_file()]
    if not matches:
        raise FileNotFoundError(f"No se generó ningún archivo .{extension}")
    return sorted(matches, key=lambda path: path.name)


async def set_commands(application: Application) -> None:
    await application.bot.set_my_commands(
        [
            BotCommand("restart", "Ver instrucciones"),
        ]
    )
    await application.bot.set_chat_menu_button(menu_button=MenuButtonCommands())


def main() -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("Falta TELEGRAM_BOT_TOKEN")

    request = HTTPXRequest(
        read_timeout=UPLOAD_TIMEOUT_SECONDS,
        write_timeout=UPLOAD_TIMEOUT_SECONDS,
        media_write_timeout=UPLOAD_TIMEOUT_SECONDS,
    )
    application = Application.builder().token(token).request(request).post_init(set_commands).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("restart", restart))
    application.add_handler(CommandHandler("cancel", cancel))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))

    logger.info("dinpyupbot started")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
