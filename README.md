# 🚀 Z-Downloader: Multi-Platform Video Downloader

**Z-Downloader** es una herramienta profesional de escritorio basada en web para la descarga de videos de **YouTube** y **TikTok** con la máxima calidad disponible. Diseñada para ser simple, rápida y totalmente portable.

---

##  Características Principales

*   **Soporte Multi-Plataforma:** Compatible con YouTube (Videos, Shorts, Playlists) y TikTok.
*   **Calidad Ultra Digital:** Descarga hasta en 4K/8K (donde esté disponible) y modo **Podcast** (MP3/WAV alta fidelidad).
*   **Zero-Config (FFmpeg Auto-Gestionado):** No necesitas instalar FFmpeg manualmente. El motor lo detecta y configura automáticamente para Windows, Mac y Linux.
*   **Gestión de Datos Inteligente:** Limpieza automática de metadatos huérfanos y almacenamiento organizado en carpetas `Z-Data`.
*   **Interfaz Moderna:** Construida con Streamlit para una experiencia de usuario fluida y visualmente atractiva.

---

## 🛠️ Instalación y Uso Rápido

No requiere configuración técnica complicada. Solo descarga el repositorio y ejecuta el script de inicio según tu sistema operativo:

### 🪟 Windows
1. Haz doble clic en `iniciar_windows.bat`.
2. El script creará el entorno virtual e instalará las dependencias automáticamente.

### 🍎 macOS
1. Abre una terminal en la carpeta del proyecto.
2. Ejecuta: `sh iniciar_mac.command`.

### 🐧 Linux
1. Abre una terminal en la carpeta del proyecto.
2. Ejecuta: `sh iniciar_linux.sh`.

---

##   Tecnologías Utilizadas

*   **Python 3.x**
*   **Streamlit:** Interfaz de usuario.
*   **yt-dlp:** Motor de extracción de alto rendimiento.
*   **static-ffmpeg:** Gestión automatizada de binarios multimedia.
*   **curl-cffi:** Impersonation de navegador para saltar restricciones de TikTok.

---

##   Estructura del Proyecto

*   `app.py`: Interfaz de usuario y lógica de Streamlit.
*   `core.py`: Motor principal de descarga y procesamiento.
*   `Descargas_Z/`: Carpeta donde aparecerán tus videos.
*   `Z-Data/`: Almacenamiento interno de logs y metadatos.

---
 