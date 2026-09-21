@echo off
setlocal
cd /d "%~dp0"

if not exist "venv\Scripts\python.exe" (
    if exist "venv" (
        echo El entorno virtual existente no es valido para Windows, recreando...
        rmdir /s /q venv
    )
    python -m venv venv
    if errorlevel 1 (
        echo ERROR: no se pudo crear el entorno virtual. Verifica que Python este instalado y en el PATH.
        exit /b 1
    )
)

call venv\Scripts\activate.bat
if errorlevel 1 (
    echo ERROR: no se pudo activar el entorno virtual.
    exit /b 1
)

python -m pip install --upgrade pip
python -m pip install -r requirements.txt pyinstaller
if errorlevel 1 (
    echo ERROR: fallo la instalacion de dependencias.
    exit /b 1
)

python -m PyInstaller build.spec --clean
if errorlevel 1 (
    echo ERROR: fallo la compilacion con PyInstaller.
    exit /b 1
)

echo.
echo Build OK: dist\infohub-file-manager.exe
echo Run with: dist\infohub-file-manager.exe
endlocal
