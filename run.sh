#!/bin/bash
# ALERJ — Sistema de Acompanhamento Legislativo
# Script de inicialização para macOS e Linux

# Vai para a pasta do script
cd "$(dirname "$0")"

echo "==============================================="
echo "  ALERJ - Sistema de Acompanhamento Legislativo"
echo "==============================================="
echo ""

# Verifica Python 3
if ! command -v python3 &>/dev/null; then
    echo "[ERRO] Python 3 não encontrado."
    echo "  macOS:  brew install python3"
    echo "  Linux:  sudo apt install python3 python3-pip"
    exit 1
fi

PYTHON=python3

# Verifica pip
if ! $PYTHON -m pip --version &>/dev/null; then
    echo "[ERRO] pip não encontrado. Instale com: $PYTHON -m ensurepip"
    exit 1
fi

# Instala dependências na primeira execução
if [ ! -f ".deps_ok" ]; then
    echo "Instalando dependências (primeira execução, aguarde)..."
    $PYTHON -m pip install -r requirements.txt --quiet
    if [ $? -ne 0 ]; then
        echo "[ERRO] Falha ao instalar dependências."
        exit 1
    fi
    touch .deps_ok
    echo "Dependências instaladas!"
    echo ""
fi

# Inicia o Streamlit
echo "Iniciando a interface..."
echo "Acesse no navegador: http://localhost:8501"
echo ""
echo "Para encerrar: pressione CTRL+C nesta janela."
echo ""

$PYTHON -m streamlit run app.py \
    --server.port 8501 \
    --server.headless false \
    --browser.gatherUsageStats false
