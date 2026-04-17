#!/usr/bin/env bash

# Evitar que se cierre de inmediato en caso de error en algunas lineas clave
set -e

# Asegurar que estamos en el directorio del script
cd "$(dirname "$0")"

VENV_DIR=".venv"

echo "=========================================="
echo "          Iniciando Z-Downloader"
echo "=========================================="
echo ""

# Buscar Python 3
if command -v python3 &>/dev/null; then
    PYTHON_EXE="python3"
elif command -v python &>/dev/null && python --version 2>&1 | grep -q "Python 3"; then
    PYTHON_EXE="python"
else
    echo "[ERROR] No se encontró Python 3 en este equipo."
    echo "Instala Python 3 y vuelve a ejecutar este archivo."
    echo "Presiona Enter para salir..."
    read dummy
    exit 1
fi


# Crear entorno virtual
if [ ! -f "$VENV_DIR/bin/python" ] && [ ! -f "$VENV_DIR/bin/python3" ]; then
    echo "[1/4] Creando entorno virtual..."
    "$PYTHON_EXE" -m venv "$VENV_DIR" || {
        echo "[ERROR] No se pudo crear el entorno virtual."
        echo "Asegúrate de instalar dependencias de sistema necesarias."
        echo "Presiona Enter para salir..."
        read dummy
        exit 1
    }
else
    echo "[1/4] Entorno virtual detectado."
fi

# Activar entorno virtual
echo "[2/4] Activando entorno virtual..."
source "$VENV_DIR/bin/activate" || {
    echo "[ERROR] No se pudo activar el entorno virtual."
    echo "Presiona Enter para salir..."
    read dummy
    exit 1
}

# Actualizar pip
echo "[3/4] Actualizando pip..."
python -m pip install --upgrade pip

# Instalar dependencias
echo "[4/4] Instalando dependencias..."
python -m pip install -r requirements.txt || {
    echo "[ERROR] Fallo al instalar requirements.txt."
    echo "Presiona Enter para salir..."
    read dummy
    exit 1
}

# Crear directorio de descargas
mkdir -p "Descargas_Z"

echo ""
echo "Lanzando interfaz web..."
echo "Si el navegador no se abre solo, copia la URL local que mostrará Streamlit."
echo ""
python -m streamlit run app.py || {
    echo ""
    echo "[ERROR] Streamlit no pudo iniciarse correctamente."
    echo "Presiona Enter para salir..."
    read dummy
    exit 1
}
