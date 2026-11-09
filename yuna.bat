@echo off
rem ══════════════════════════════════════════════════════════════════
rem  Yuna — Bot de Musica do Discord (SAO: Ordinal Scale)
rem  Launcher: inicia o bot usando o venv já instalado uma única vez.
rem  Duplo clique (ou pelo atalho "Yuna" na Área de Trabalho).
rem ══════════════════════════════════════════════════════════════════
title Yuna - Bot de Musica (SAO)
cd /d "C:\Users\gusta\Desktop\sla\yuna"

if not exist ".\venv\Scripts\python.exe" (
    echo.
    echo [!] O venv nao existe. Rode uma vez no terminal:
    echo     python -m venv venv
    echo     venv\Scripts\pip install -r requirements.txt
    echo.
    pause
    exit /b 1
)

if not exist ".env" (
    echo.
    echo [!] O arquivo .env nao existe. Copie .env.example para .env,
    echo     cole o DISCORD_TOKEN e tente de novo.
    echo.
    pause
    exit /b 1
)

echo Iniciando a Yuna... (feche ESTA janela para encerrar o bot)
echo.
call ".\venv\Scripts\python.exe" main.py

echo.
echo A Yuna encerrou.
pause
