@echo off
chcp 65001 >nul
title ALERJ - Acompanhamento Legislativo

echo ===============================================
echo   ALERJ - Sistema de Acompanhamento Legislativo
echo ===============================================
echo.

:: Verifica se Python esta disponivel
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERRO] Python nao encontrado. Instale em: https://www.python.org/downloads/
    pause
    exit /b 1
)

:: Instala dependencias se necessario
if not exist "%~dp0.deps_ok" (
    echo Instalando dependencias (primeira execucao, aguarde)...
    python -m pip install -r "%~dp0requirements.txt" --quiet
    if errorlevel 1 (
        echo [ERRO] Falha ao instalar dependencias.
        pause
        exit /b 1
    )
    echo. > "%~dp0.deps_ok"
    echo Dependencias instaladas!
    echo.
)

:: Inicia o Streamlit
echo Iniciando a interface...
echo Acesse no navegador: http://localhost:8501
echo.
echo Para encerrar: pressione CTRL+C nesta janela.
echo.

cd /d "%~dp0"
python -m streamlit run app.py --server.port 8501 --server.headless false --browser.gatherUsageStats false

pause
