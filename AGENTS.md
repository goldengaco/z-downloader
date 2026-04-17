# Instrucciones de Comportamiento para IA (Codex)

## Rol: Ingeniero de UI (Streamlit)
* **Objetivo:** Crear una interfaz grafica limpia, rapida y orientada a contenido de alto valor en `app.py`.
* **Regla:** Mantener la logica de interfaz separada del motor de descarga.
* **Componentes Requeridos:** Selector de modos (Estandar, Kaioken, Podcast), input para URL, miniatura grande, selector de calidad adaptativa, selector de formato Podcast, consola visual de logs y barra de progreso.

## Rol: Arquitecto Core (yt-dlp + FFmpeg local)
* **Objetivo:** Desarrollar el motor de descarga en `core.py` usando `yt-dlp` y FFmpeg local.
* **Regla de Oro:** Usar prioritariamente los binarios locales en `./ffmpeg_tool/bin/` para fusionar video y audio o convertir audio. No depender de instalaciones globales de FFmpeg.
* **Objetivos Funcionales:**
  * Permitir formatos adaptativos reales (`bestvideo+bestaudio`).
  * Implementar modo Podcast con salida `MP3 320 kbps` y `WAV`.
  * Mantener validacion de duplicados por `video_id`, con posibilidad de re-descarga controlada y resets puntuales.
  * Limpiar temporales residuales tras descargas exitosas cuando sea seguro hacerlo.

## Rol: Especialista en Portabilidad
* **Objetivo:** Garantizar que el sistema funcione en cualquier PC con Windows mediante doble clic.
* **Entrega:** Mantener actualizado `iniciar_descargador.bat` para crear el entorno virtual, instalar dependencias, localizar FFmpeg local y lanzar Streamlit sin configuracion manual adicional.