# dinpyupbot

Bot de Telegram que convierte vídeos y listas de **YouTube** en **MP3** y te los envía al chat. Incluye un panel web sencillo para controlarlo.

## Características

- Acepta enlaces de vídeos sueltos y de listas de reproducción.
- **No descarga Shorts.** Si un enlace es un Short, lo rechaza. En una lista, se salta los Shorts y solo procesa el resto.
- Genera siempre audio en MP3.
- Límite de tamaño por archivo: unos **48 MB** (configurable), para que Telegram pueda enviarlo sin problemas.
- Panel web para ver el estado, arrancar o parar el servicio y consultar actividad reciente.

## Librerías principales

- [python-telegram-bot](https://github.com/python-telegram-bot/python-telegram-bot) — comunicación con Telegram  
- [yt-dlp](https://github.com/yt-dlp/yt-dlp) — descarga desde YouTube  
- [imageio-ffmpeg](https://github.com/imageio/imageio-ffmpeg) — conversión a MP3  
- [python-dotenv](https://github.com/theskumar/python-dotenv) — variables de entorno  

El resto de dependencias está en el propio proyecto.

## Cómo instalarlo con tu agente de IA

Si usas un agente (Grok, ChatGPT, Claude, etc.) con acceso a tu máquina o por SSH, puedes pedírselo así:

1. **Facilítale primero el acceso a tu máquina** (claves SSH u otra forma de conexión que ya uses con el agente).  
2. **Pídele que clone este repositorio** en esa máquina.  
3. **Sustituye el token** del bot por el de tu propio bot de Telegram.  
4. Si no te gusta el nombre original, **pídele que elimine o cambie todas las referencias** al nombre del bot del repositorio.  
5. **Pídele que instale todo lo necesario**, deje el bot en marcha y exponga el panel con un **túnel de Cloudflare**:  
   - uno **temporal sin cuenta** (quick tunnel), o  
   - uno **con cuenta**, si ya tienes Cloudflare configurado.  

## Gracias por ver

Gracias por ver o usar este repositorio.
💛
