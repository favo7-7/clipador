@echo off
cd /d "%~dp0"
call .venv\Scripts\activate.bat
set CLIPADOR_MAX_MINUTES=120
set CLIPADOR_MAX_UPLOAD_MB=2000
set CLIPADOR_MODEL=small
echo Iniciando o Clipador... o navegador abre sozinho em instantes.
echo Deixe esta janela aberta enquanto usa. Para desligar, feche a janela ou aperte Ctrl+C.
start "" cmd /c "timeout /t 4 /nobreak >nul & start http://127.0.0.1:8000"
python -m clipador serve
pause
