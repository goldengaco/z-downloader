@echo off
setlocal EnableExtensions
title Z-Downloader

cd /d "%~dp0"

set "VENV_DIR=%~dp0.venv"
set "PYTHON_EXE="
echo ==========================================
echo           Iniciando Z-Downloader
echo ==========================================
echo.

where py >nul 2>&1
if %errorlevel%==0 (
    set "PYTHON_EXE=py -3"
) else (
    where python >nul 2>&1
    if %errorlevel%==0 (
        set "PYTHON_EXE=python"
    )
)

if not defined PYTHON_EXE (
    echo [ERROR] No se encontro Python 3 en este equipo.
    echo Instala Python 3 y vuelve a ejecutar este archivo.
    echo.
    pause
    exit /b 1
)


if not exist "%VENV_DIR%\Scripts\python.exe" (
    echo [1/4] Creando entorno virtual...
    call %PYTHON_EXE% -m venv "%VENV_DIR%"
    if errorlevel 1 (
        echo [ERROR] No se pudo crear el entorno virtual.
        echo.
        pause
        exit /b 1
    )
) else (
    echo [1/4] Entorno virtual detectado.
)

echo [2/4] Activando entorno virtual...
call "%VENV_DIR%\Scripts\activate.bat"
if errorlevel 1 (
    echo [ERROR] No se pudo activar el entorno virtual.
    echo.
    pause
    exit /b 1
)

echo [3/4] Actualizando pip...
python -m pip install --upgrade pip
if errorlevel 1 (
    echo [ERROR] Fallo al actualizar pip.
    echo.
    pause
    exit /b 1
)

echo [4/4] Instalando dependencias...
python -m pip install -r requirements.txt
if errorlevel 1 (
    echo [ERROR] Fallo al instalar requirements.txt.
    echo.
    pause
    exit /b 1
)

if not exist "%~dp0Descargas_Z" (
    mkdir "%~dp0Descargas_Z"
)

echo.
echo ==========================================
echo    Todo listo! Lanzando Z-Downloader...
echo ==========================================
echo.
echo Veras 3 direcciones (URLs). Aqui te explicamos para que sirve cada una:
echo.
echo  - Local URL: Abre esta en tu navegador (Chrome, Edge, etc.) para usar
echo    el descargador en ESTA computadora. Es la principal.
echo.
echo  - Network URL: Copia esta direccion en tu celular o tablet conectado
echo    al mismo Wi-Fi y podras descargar desde ahi usando tu PC.
echo.
echo  - External URL: Es tu direccion publica de internet. Solo funciona
echo    si abres puertos en tu modem/router (uso avanzado).
echo.
echo NO cierres esta ventana mientras uses el programa.
echo Cuando termines, cierra esta ventana para apagar Z-Downloader.
echo.
python -m streamlit run app.py

if errorlevel 1 (
    echo.
    echo [ERROR] Streamlit no pudo iniciarse correctamente.
    pause
    exit /b 1
)

endlocal
