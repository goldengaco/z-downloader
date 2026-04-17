# 🚀 Z-Downloader

**Descarga videos de YouTube y TikTok** en la mejor calidad disponible, directo a tu computadora. Sin complicaciones, sin registro, sin límites.

---

## ¿Qué es Z-Downloader?

Es un programa que corre en tu propia computadora y te permite descargar videos de YouTube y TikTok con solo pegar el enlace. Funciona en **Windows**, **Mac** y **Linux**.

**No necesitas instalar nada extra.** El programa se encarga de preparar todo por ti la primera vez que lo abras.

---

## ¿Cómo se usa? (3 pasos)

### Paso 1: Abre el programa
Haz doble clic en el archivo de inicio según tu sistema:

| Sistema | Archivo que debes abrir |
|---------|------------------------|
| Windows | `iniciar_windows.bat` |
| Mac     | `iniciar_mac.command` |
| Linux   | Ejecuta en terminal: `sh iniciar_linux.sh` |

> La primera vez tardará un poco más porque descarga las herramientas necesarias. Las siguientes veces abrirá mucho más rápido.

### Paso 2: Pega el enlace del video
Se abrirá una página web en tu navegador (Chrome, Edge, Firefox, etc.). Ahí solo tienes que:
1. Copiar el enlace del video de YouTube o TikTok.
2. Pegarlo en el campo de texto.
3. Elegir la calidad que prefieras.

### Paso 3: Descarga
Dale clic al botón de descargar y espera. Tu video aparecerá en la carpeta **`Descargas_Z`** dentro de la carpeta del programa.

---

## Modos de descarga

| Modo | ¿Para qué sirve? |
|------|-------------------|
| **Standard** | Descargas normales. Tú eliges la calidad del video (360p, 720p, 1080p, etc.) |
| **Kaioken** | Descarga automática en la **máxima calidad disponible** (hasta 4K/8K) con la mayor velocidad posible |
| **Podcast** | Extrae únicamente el **audio** del video en alta fidelidad (MP3 o WAV). Ideal para música o entrevistas |

---

## Preguntas Frecuentes

**¿Dónde quedan mis videos descargados?**
En la carpeta `Descargas_Z` que se crea automáticamente dentro de la carpeta del programa.

**¿Puedo descargar solo el audio de un video?**
Sí. Usa el modo **Podcast** y obtendrás el audio en MP3 o WAV de alta calidad.

**¿Funciona con playlists de YouTube?**
Sí. Si pegas el enlace de una playlist, descargará todos los videos disponibles.

**¿El programa instala algo en mi computadora?**
No. Todo vive dentro de su propia carpeta. Si quieres desinstalar Z-Downloader, simplemente borra la carpeta y listo. No deja rastro en tu sistema.

**¿Necesito instalar FFmpeg?**
No. El programa lo descarga e instala automáticamente en segundo plano la primera vez.

**¿Qué pasa si borro un video descargado por accidente?**
No hay problema. El programa detecta que el archivo ya no existe y te permitirá volver a descargarlo sin errores.

---

## Requisitos

Solo necesitas tener **Python 3** instalado en tu computadora. Si no lo tienes:
- **Windows:** Descárgalo desde [python.org](https://www.python.org/downloads/) (marca la casilla "Add Python to PATH" durante la instalación).
- **Mac:** Descárgalo desde [python.org](https://www.python.org/downloads/) o instálalo con `brew install python3`.
- **Linux (Ubuntu/Debian):** Ejecuta `sudo apt install python3 python3-venv`.

---

## Para desarrolladores

### Tecnologías utilizadas
- **Python 3** — Lenguaje base
- **Streamlit** — Interfaz de usuario web
- **yt-dlp** — Motor de extracción y descarga
- **static-ffmpeg** — Gestión automatizada de binarios multimedia
- **curl-cffi** — Impersonation de navegador para compatibilidad con TikTok

### Estructura del proyecto
| Archivo/Carpeta | Descripción |
|-----------------|-------------|
| `app.py` | Interfaz de usuario (lo que ves en el navegador) |
| `core.py` | Motor principal de descarga y procesamiento |
| `Descargas_Z/` | Aquí aparecen los videos descargados |
| `Z-Data/` | Datos internos del programa (logs, metadatos) |
| `.streamlit/` | Configuración de la interfaz web |