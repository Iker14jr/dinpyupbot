#!/usr/bin/env python3
"""Panel de control web para dinpyupbot."""

import html
import json
import os
import subprocess
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

BASE_DIR = Path(__file__).resolve().parent
PID_FILE = BASE_DIR / "dinpyupbot.pid"
DOWNLOADS_LOG = BASE_DIR / "downloads.log"
ERRORS_LOG = BASE_DIR / "errors.log"
USERS_FILE = BASE_DIR / "users.json"
START_SCRIPT = BASE_DIR / "start.sh"
STOP_SCRIPT = BASE_DIR / "stop.sh"
ENV_FILE = BASE_DIR / ".env"
PORT = int(os.getenv("CONTROL_PANEL_PORT", "9876"))


def is_running():
    if not PID_FILE.exists():
        return False, None
    try:
        pid = int(PID_FILE.read_text().strip())
        os.kill(pid, 0)
        return True, pid
    except (ProcessLookupError, ValueError, PermissionError, OSError):
        return False, None


def read_tail_lines(path: Path, max_lines: int = 30):
    if not path.exists():
        return []
    try:
        lines = path.read_text(errors="replace").splitlines()
        return [ln for ln in lines if ln.strip()][-max_lines:]
    except Exception:
        return []


def parse_event_line(line: str):
    parts = [p.strip() for p in line.split("|")]
    if len(parts) < 3:
        return {"raw": line}
    return {"ts": parts[0], "user": parts[1], "detail": " | ".join(parts[2:])}


def load_users():
    if not USERS_FILE.exists():
        return {}
    try:
        return json.loads(USERS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_users(data):
    USERS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def get_token():
    if not ENV_FILE.exists():
        return ""
    for line in ENV_FILE.read_text().splitlines():
        if line.startswith("TELEGRAM_BOT_TOKEN="):
            return line.split("=", 1)[1].strip()
    return ""


def token_hint():
    token = get_token()
    if not token:
        return "no configurado"
    parts = token.split(":")
    if len(parts) == 2:
        return f"{parts[0][:4]}…:{parts[1][:6]}…"
    return token[:12] + "…"


def telegram_api(method, payload):
    token = get_token()
    if not token:
        return {"ok": False, "description": "sin token"}
    url = f"https://api.telegram.org/bot{token}/{method}"
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        return {"ok": False, "description": str(e)}


def clear_user_chat(user_id: str):
    data = load_users()
    entry = data.get(str(user_id))
    if not entry:
        return False, "Usuario no encontrado"
    chat_id = entry.get("chat_id") or entry.get("id")
    msg_ids = list(entry.get("message_ids") or [])
    deleted = 0
    for mid in msg_ids:
        res = telegram_api("deleteMessage", {"chat_id": chat_id, "message_id": mid})
        if res.get("ok"):
            deleted += 1
    # also try to send a clean notice then delete it quickly is optional
    entry["message_ids"] = []
    entry["cleared_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    data[str(user_id)] = entry
    save_users(data)
    return True, f"Limpiados {deleted} mensajes de {entry.get('full_name') or user_id}"


def render_events(title, lines, css_class):
    if not lines:
        return ""
    items = []
    for line in reversed(lines):
        ev = parse_event_line(line)
        if "raw" in ev:
            items.append(f'<div class="event">{html.escape(ev["raw"])}</div>')
        else:
            items.append(
                f'<div class="event">'
                f'<div class="event-ts">{html.escape(ev["ts"])}</div>'
                f'<div class="event-user">{html.escape(ev["user"])}</div>'
                f'<div class="event-detail">{html.escape(ev["detail"])}</div>'
                f"</div>"
            )
    return f'''
    <div class="card {css_class}">
      <div class="log-header">
        <h2>{html.escape(title)}</h2>
        <span class="meta">{len(lines)} registro(s)</span>
      </div>
      <div class="events">{"".join(items)}</div>
    </div>'''


def render_users():
    users = load_users()
    if not users:
        return ""
    rows = []
    for uid, u in sorted(users.items(), key=lambda x: x[1].get("last_seen", ""), reverse=True):
        name = html.escape(u.get("full_name") or "sin nombre")
        uname = u.get("username") or ""
        uname_html = f"@{html.escape(uname)}" if uname else "sin_username"
        last = html.escape(u.get("last_seen") or "?")
        first = html.escape(u.get("first_seen") or "?")
        rows.append(
            f'<div class="user-row">'
            f'<div class="user-info">'
            f'<div class="event-user">{name} <span class="meta">({uname_html})</span></div>'
            f'<div class="meta">id={html.escape(str(uid))} · visto {last} · desde {first}</div>'
            f'</div>'
            f'<a class="btn btn-clear" href="/clear?uid={quote(str(uid))}">Borrar chat</a>'
            f'</div>'
        )
    return f'''
    <div class="card users">
      <div class="log-header">
        <h2>Usuarios que han hablado con el bot</h2>
        <span class="meta">{len(users)} usuario(s)</span>
      </div>
      <div class="user-list">{"".join(rows)}</div>
    </div>'''


def render_page(message=None, success=None):
    running, pid = is_running()
    downloads = read_tail_lines(DOWNLOADS_LOG, 1)
    errors = read_tail_lines(ERRORS_LOG, 25)

    status_class = "running" if running else "stopped"
    status_text = "Activo" if running else "Detenido"
    pid_html = f'<div class="pid">PID {pid}</div>' if running and pid else ""

    start_disabled = "disabled" if running else ""
    stop_disabled = "" if running else "disabled"

    msg_html = ""
    if message:
        cls = "ok" if success else "err"
        msg_html = f'<div class="message {cls}">{html.escape(message)}</div>'

    downloads_html = render_events("Última descarga", downloads, "downloads")
    errors_html = render_events("Errores / fallos", errors, "errors")
    users_html = render_users()

    empty_note = ""
    if not downloads and not errors and not users_html:
        empty_note = '<div class="card"><p class="meta">Todavía no hay actividad registrada.</p></div>'

    return f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>dinpyupbot – Panel</title>
  <style>
    :root {{
      --bg: #0f1419; --card: #1a2332; --text: #e7e9ea; --muted: #8b98a5;
      --green: #00ba7c; --red: #f4212e; --blue: #1d9bf0; --border: #2f3336;
    }}
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      background: var(--bg); color: var(--text); min-height: 100vh;
      padding: 24px; line-height: 1.5;
    }}
    .container {{ max-width: 960px; margin: 0 auto; }}
    h1 {{ font-size: 1.5rem; margin-bottom: 6px; }}
    .subtitle {{ color: var(--muted); margin-bottom: 24px; font-size: 0.95rem; }}
    .card {{
      background: var(--card); border: 1px solid var(--border);
      border-radius: 12px; padding: 18px; margin-bottom: 18px;
    }}
    .status-row {{ display: flex; align-items: center; gap: 12px; margin-bottom: 14px; }}
    .dot {{ width: 12px; height: 12px; border-radius: 50%; }}
    .dot.running {{ background: var(--green); box-shadow: 0 0 8px var(--green); }}
    .dot.stopped {{ background: var(--red); }}
    .status-text {{ font-weight: 600; font-size: 1.1rem; }}
    .pid {{ color: var(--muted); font-size: 0.9rem; }}
    .buttons {{ display: flex; gap: 12px; flex-wrap: wrap; }}
    button, .btn {{
      border: none; border-radius: 999px; padding: 10px 22px;
      font-size: 0.95rem; font-weight: 600; cursor: pointer;
      text-decoration: none; display: inline-block; color: inherit;
    }}
    button:disabled, .btn.disabled {{ opacity: 0.4; pointer-events: none; }}
    .btn-start {{ background: var(--green); color: #000; }}
    .btn-stop  {{ background: var(--red); color: #fff; }}
    .btn-refresh {{ background: var(--blue); color: #fff; }}
    .btn-clear {{ background: #3a2730; color: #ff8a9a; border: 1px solid rgba(244,33,46,0.35); padding: 8px 14px; font-size: 0.85rem; }}
    .log-header {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }}
    .log-header h2 {{ font-size: 1.05rem; }}
    .meta {{ color: var(--muted); font-size: 0.85rem; }}
    .message {{ margin-top: 12px; padding: 10px 14px; border-radius: 8px; font-size: 0.9rem; }}
    .message.ok {{ background: rgba(0,186,124,0.15); color: var(--green); }}
    .message.err {{ background: rgba(244,33,46,0.15); color: var(--red); }}
    .events, .user-list {{ display: flex; flex-direction: column; gap: 10px; max-height: 420px; overflow-y: auto; }}
    .event, .user-row {{
      background: #0b1018; border: 1px solid var(--border); border-radius: 8px;
      padding: 10px 12px; font-size: 0.88rem;
    }}
    .user-row {{ display: flex; justify-content: space-between; align-items: center; gap: 12px; flex-wrap: wrap; }}
    .event-ts {{ color: var(--muted); font-size: 0.8rem; }}
    .event-user {{ font-weight: 600; }}
    .event-detail {{ color: #c9d1d9; word-break: break-all; }}
    .card.errors .event {{ border-color: rgba(244,33,46,0.35); }}
    .card.downloads .event {{ border-color: rgba(0,186,124,0.25); }}
  </style>
</head>
<body>
  <div class="container">
    <h1>dinpyupbot</h1>
    <p class="subtitle">Panel de control · arranca, para y consulta actividad</p>

    <div class="card">
      <div class="status-row">
        <div class="dot {status_class}"></div>
        <div>
          <div class="status-text">{status_text}</div>
          {pid_html}
        </div>
      </div>
      <div class="buttons">
        <a class="btn btn-start {('disabled' if running else '')}" href="/action?op=start">Arrancar bot</a>
        <a class="btn btn-stop {('' if running else 'disabled')}" href="/action?op=stop">Parar bot</a>
        <a href="/" class="btn btn-refresh">Actualizar</a>
      </div>
      {msg_html}
    </div>

    {users_html}
    {downloads_html}
    {errors_html}
    {empty_note}

    <p class="meta" style="margin-top: 8px;">Token: {token_hint()}</p>
  </div>
</body>
</html>"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def send_html(self, content, code=200):
        data = content.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def send_text(self, content, code=200):
        data = content.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def redirect(self, msg, ok=True):
        self.send_response(302)
        self.send_header("Location", f"/?msg={quote(msg)}&ok={'1' if ok else '0'}")
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)

        if parsed.path == "/":
            msg = qs.get("msg", [None])[0]
            ok = qs.get("ok", ["0"])[0] == "1"
            self.send_html(render_page(message=msg, success=ok))
            return

        if parsed.path == "/api/status":
            running, pid = is_running()
            self.send_text(f'{{"running": {str(running).lower()}, "pid": {pid if pid else "null"}}}')
            return

        if parsed.path == "/action":
            op = qs.get("op", [""])[0]
            if op == "start":
                running, _ = is_running()
                if running:
                    self.redirect("El bot ya está en marcha", False)
                    return
                try:
                    result = subprocess.run(
                        ["bash", str(START_SCRIPT)],
                        cwd=str(BASE_DIR),
                        capture_output=True,
                        text=True,
                        timeout=20,
                    )
                    time.sleep(0.8)
                    msg = (result.stdout or result.stderr or "Bot arrancado").strip()
                    self.redirect(msg, result.returncode == 0)
                except Exception as e:
                    self.redirect(str(e)[:150], False)
                return
            if op == "stop":
                running, _ = is_running()
                if not running:
                    self.redirect("El bot no estaba en marcha", False)
                    return
                try:
                    result = subprocess.run(
                        ["bash", str(STOP_SCRIPT)],
                        cwd=str(BASE_DIR),
                        capture_output=True,
                        text=True,
                        timeout=10,
                    )
                    msg = (result.stdout or result.stderr or "Bot detenido").strip()
                    self.redirect(msg, True)
                except Exception as e:
                    self.redirect(str(e)[:150], False)
                return
            self.redirect("Acción desconocida", False)
            return

        if parsed.path == "/clear":
            uid = qs.get("uid", [""])[0]
            ok, msg = clear_user_chat(uid)
            self.redirect(msg, ok)
            return

        self.send_text("Not found", 404)


def main():
    server = HTTPServer(("0.0.0.0", PORT), Handler)
    print(f"Panel de control escuchando en http://0.0.0.0:{PORT}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
