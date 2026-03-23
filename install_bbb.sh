#!/bin/bash
# install_bbb.sh
# ===============
# Installs all dependencies for the MAB scheduler on BeagleBone Black.
# Compiles Python 3.11 from source (required due to PEP 668).
#
# WARNING: Compilation takes ~30 minutes without optimizations.
#          Add --enable-optimizations to ./configure for a faster binary
#          (~90 minutes extra build time).
#
# Usage:
#   chmod +x install_bbb.sh
#   ./install_bbb.sh

set -e

echo "======================================================"
echo " MAB Scheduler — BeagleBone Black Worker Setup"
echo "======================================================"
echo " Warning: Python 3.11 compilation takes ~30 minutes."
echo "======================================================"

PYTHON_VERSION="3.11.9"
VENV_DIR="/home/debian/thingsboardenv"

# ── 1. System dependencies ─────────────────────────────────
echo ""
echo "[1/5] Installing system dependencies..."
sudo apt update -qq
sudo apt install -y \
    wget build-essential gcc make \
    libssl-dev zlib1g-dev \
    libncurses5-dev libncursesw5-dev \
    libreadline-dev libsqlite3-dev \
    libgdbm-dev libdb5.3-dev \
    libbz2-dev libexpat1-dev \
    liblzma-dev libffi-dev \
    uuid-dev \
    libopenblas-dev   # required for NumPy

# ── 2. Python 3.11 from source ────────────────────────────
echo ""
echo "[2/5] Building Python ${PYTHON_VERSION} from source..."

if command -v python3.11 &>/dev/null; then
    echo "  Python 3.11 already installed — skipping build."
else
    cd /tmp
    TARBALL="Python-${PYTHON_VERSION}.tgz"

    if [ ! -f "$TARBALL" ]; then
        echo "  Downloading Python ${PYTHON_VERSION}..."
        wget -q --show-progress \
            "https://www.python.org/ftp/python/${PYTHON_VERSION}/${TARBALL}"
    fi

    echo "  Extracting..."
    tar -xzf "$TARBALL"
    cd "Python-${PYTHON_VERSION}"

    echo "  Configuring (without --enable-optimizations to save ~60 min)..."
    ./configure

    echo "  Compiling with $(nproc) core(s) — this will take ~30 minutes..."
    make -j$(nproc)

    echo "  Installing..."
    sudo make altinstall   # installs as python3.11, does NOT replace python3

    echo "  Python 3.11 installed."
    python3.11 --version
fi

# ── 3. Virtual environment ─────────────────────────────────
echo ""
echo "[3/5] Setting up Python virtual environment..."

if [ -d "$VENV_DIR" ]; then
    echo "  Virtual environment already exists at $VENV_DIR"
else
    python3.11 -m venv "$VENV_DIR"
    echo "  Created virtual environment at $VENV_DIR"
fi

source "$VENV_DIR/bin/activate"
pip install --upgrade pip -q
pip install paho-mqtt psutil numpy
deactivate

echo "  Packages installed in $VENV_DIR"

# ── 4. Verify ──────────────────────────────────────────────
echo ""
echo "[4/5] Verifying installation..."

"$VENV_DIR/bin/python" -c "
import paho.mqtt.client as mqtt
import psutil
import numpy as np
print(f'  paho-mqtt: OK')
print(f'  psutil:    OK  (cores={psutil.cpu_count()})')
print(f'  numpy:     OK  (v{np.__version__})')
"

# ── 5. Systemd service (optional) ─────────────────────────
echo ""
echo "[5/5] Setting up systemd service..."

AGENT_PATH="$(pwd)/tb_agent.py"
if [ ! -f "$AGENT_PATH" ]; then
    AGENT_PATH="/home/debian/tb_agent.py"
fi

SERVICE_FILE="/etc/systemd/system/tb-agent.service"

if [ -f "$SERVICE_FILE" ]; then
    echo "  Service already exists — skipping."
else
sudo tee "$SERVICE_FILE" > /dev/null << EOF
[Unit]
Description=ThingsBoard MAB Agent
After=network.target

[Service]
ExecStart=$VENV_DIR/bin/python $AGENT_PATH
Restart=always
RestartSec=5
User=debian
WorkingDirectory=/home/debian

[Install]
WantedBy=multi-user.target
EOF

    sudo systemctl daemon-reload
    echo "  Service created at $SERVICE_FILE"
fi

# ── Summary ────────────────────────────────────────────────
echo ""
echo "======================================================"
echo " Setup complete!"
echo "======================================================"
echo ""
echo "  Before running, edit tb_agent.py and set:"
echo "    TB_HOST  = '<master PC IP>'"
echo "    TB_TOKEN = '<device token from ThingsBoard>'"
echo "    NODE_ID  = 'bbb'"
echo ""
echo "  IMPORTANT: Always run from /home/debian to avoid"
echo "  Python finding the source directory instead of the"
echo "  installed package:"
echo "    cd /home/debian"
echo "    $VENV_DIR/bin/python tb_agent.py"
echo ""
echo "  To enable auto-start on boot:"
echo "    sudo systemctl enable tb-agent"
echo "    sudo systemctl start tb-agent"
echo ""
echo "  To check logs:"
echo "    sudo journalctl -u tb-agent -f"
echo "======================================================"
