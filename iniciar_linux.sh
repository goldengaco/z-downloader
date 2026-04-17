#!/bin/sh

# Asegurar que estamos en el directorio del script
cd "$(dirname "$0")" || exit 1

VENV_DIR=".venv"

echo "=========================================="
echo "          Iniciando Z-Downloader"
echo "=========================================="
echo ""

# Buscar Python 3
PYTHON_EXE=""
if command -v python3 >/dev/null 2>&1; then
    PYTHON_EXE="python3"
elif command -v python >/dev/null 2>&1 && python --version 2>&1 | grep -q "Python 3"; then
    PYTHON_EXE="python"
fi

if [ -z "$PYTHON_EXE" ]; then
    echo "[ERROR] No se encontro Python 3 en este equipo."
    echo "Instala Python 3 y vuelve a ejecutar este archivo."
    echo "Presiona Enter para salir..."
    read dummy
    exit 1
fi

# Validar que el entorno virtual sea funcional, si existe pero esta roto, eliminarlo
if [ -d "$VENV_DIR" ] && [ ! -f "$VENV_DIR/bin/python" ] && [ ! -f "$VENV_DIR/bin/python3" ]; then
    echo "[AVISO] Entorno virtual corrupto detectado. Recreando..."
    rm -rf "$VENV_DIR"
fi

# Crear entorno virtual
if [ ! -d "$VENV_DIR" ]; then
    echo "[1/4] Creando entorno virtual..."
    "$PYTHON_EXE" -m venv "$VENV_DIR"
    if [ $? -ne 0 ]; then
        echo "[ERROR] No se pudo crear el entorno virtual."
        echo "En Ubuntu/Debian ejecuta: sudo apt install python3-venv"
        echo "Presiona Enter para salir..."
        read dummy
        exit 1
    fi
else
    echo "[1/4] Entorno virtual detectado."
fi

# Activar entorno virtual (usando . en lugar de source para compatibilidad POSIX)
echo "[2/4] Activando entorno virtual..."
. "$VENV_DIR/bin/activate"
if [ $? -ne 0 ]; then
    echo "[ERROR] No se pudo activar el entorno virtual."
    echo "Presiona Enter para salir..."
    read dummy
    exit 1
fi

# Actualizar pip
echo "[3/4] Actualizando pip..."
python -m pip install --upgrade pip

# Instalar dependencias
echo "[4/4] Instalando dependencias..."
python -m pip install -r requirements.txt
if [ $? -ne 0 ]; then
    echo "[ERROR] Fallo al instalar requirements.txt."
    echo "Presiona Enter para salir..."
    read dummy
    exit 1
fi

# Crear directorio de descargas
mkdir -p "Descargas_Z"

echo ""
echo "=========================================="
echo "   Todo listo! Lanzando Z-Downloader..."
echo "=========================================="
echo ""
echo "Veras 3 direcciones (URLs). Aqui te explicamos para que sirve cada una:"
echo ""
echo " - Local URL: Abre esta en tu navegador (Chrome, Firefox, etc.) para usar"
echo "   el descargador en ESTA computadora. Es la principal."
echo ""
echo " - Network URL: Copia esta direccion en tu celular o tablet conectado"
echo "   al mismo Wi-Fi y podras descargar desde ahi usando tu PC."
echo ""
echo " - External URL: Es tu direccion publica de internet. Solo funciona"
echo "   si abres puertos en tu modem/router (uso avanzado)."
echo ""
echo "NO cierres esta ventana mientras uses el programa."
echo "Cuando termines, cierra esta ventana para apagar Z-Downloader."
echo ""
python -m streamlit run app.py
if [ $? -ne 0 ]; then
    echo ""
    echo "[ERROR] Streamlit no pudo iniciarse correctamente."
    echo "Presiona Enter para salir..."
    read dummy
    exit 1
fi
