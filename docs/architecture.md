# Arquitectura del Sistema: Z-Downloader

## 1. Vision General
Z-Downloader es una herramienta local y portable para respaldar contenido de YouTube en alta fidelidad. La aplicacion usa Streamlit para la interfaz, yt-dlp para la extraccion y FFmpeg local embebido para fusionar video y audio o convertir audio sin depender de instalaciones globales.

## 2. Decision Arquitectonica Critica (ADR)
* **Problema:** La estrategia de solo formatos progresivos limita demasiado la calidad real disponible en YouTube moderno.
* **Solucion:** El motor usa `bestvideo+bestaudio` y delega la fusion a los binarios locales en `./ffmpeg_tool/bin/`. De esta forma mantenemos portabilidad extrema y desbloqueamos 1080p, 1440p, 4K y variantes de 60fps cuando el contenido las ofrece.

## 3. Modos de Operacion
* **Modo Estandar:** Inspecciona el video y permite elegir manualmente una calidad adaptativa concreta. Si la pista elegida no tiene audio integrado, FFmpeg local fusiona automaticamente el mejor audio disponible.
* **Modo Kaioken:** Modo extremo de alto rendimiento. Selecciona automaticamente la mejor calidad detectada, habilita parametros agresivos de descarga y prioriza una finalizacion rapida manteniendo la maxima fidelidad posible.
* **Modo Podcast:** Descarga el mejor audio disponible y permite convertirlo a `MP3 320 kbps` o `WAV` usando FFmpeg local.

## 4. Estructura de Componentes
* `app.py`: Punto de entrada de Streamlit. Maneja estado, miniaturas, selectores de calidad, modo Podcast y la consola visual de logs.
* `core.py`: Implementa `YoutubeEngine`, descubre formatos adaptativos, configura yt-dlp, usa FFmpeg local, administra progreso y persiste metadatos.
* `iniciar_descargador.bat`: Valida Python, activa el `venv`, instala dependencias y arranca la app configurando el PATH local para FFmpeg.
* `ffmpeg_tool/bin`: Ubicacion preferida para `ffmpeg.exe`, `ffprobe.exe` y utilidades asociadas. Se admite compatibilidad temporal con `ffmpeg_tool/` raiz mientras Windows permita reorganizar los binarios.
* `/Descargas_Z`: Directorio final de descargas y metadatos `.json`. Los temporales se concentran en `/Descargas_Z/_temp`.

## 5. Duplicados y Resets
* El sistema sigue usando metadatos por `video_id` para detectar descargas previas.
* El ID `b1aLqKHFGRw` esta marcado para ignorar su registro anterior y permitir una re-descarga HD con la nueva arquitectura.
* La UI tambien permite forzar re-descarga manual cuando el usuario lo decida.

## 6. Consideraciones de Fidelidad
* El contenedor preferido para fusiones adaptativas es `mkv`, ya que preserva mejor combinaciones modernas de codecs sin re-encode innecesario.
* Las miniaturas se muestran usando la mejor resolucion publicada por YouTube.
* Tras una descarga exitosa, el motor intenta limpiar temporales residuales del video para mantener el directorio ordenado.