#!/bin/bash
# install_pi.sh
# ==============
# Installs all dependencies for the MAB scheduler on Raspberry Pi 4.
#
# Usage:
#   chmod +x install_pi.sh
#   ./install_pi.sh

set -e

echo "======================================================"
echo " MAB Scheduler — Raspberry Pi Worker Setup"
echo "======================================================"

# ── 1. System dependencies ─────────────────────────────────
echo ""
echo "[1/3] Installing system dependencies..."
sudo apt update -qq
sudo apt install -y \
    python3 python3-pip python3-venv \
    libopenblas-dev

# ── 2. Python virtual environment ─────────────────────────
echo ""
echo "[2/3] Setting up Python virtual environment..."

VENV_DIR="$HOME/pienv"

if [ -d "$VENV_DIR" ]; then
    echo "  Virtual environment already exists at $VENV_DIR"
else
    python3 -m venv "$VENV_DIR"
    echo "  Created virtual environment at $VENV_DIR"
fi

source "$VENV_DIR/bin/activate"
pip install --upgrade pip -q
pip install paho-mqtt psutil numpy
deactivate

echo "  Packages installed in $VENV_DIR"

# ── 3. Systemd service (optional) ─────────────────────────
echo ""
echo "[3/3] Setting up systemd service..."

AGENT_PATH="$(pwd)/tb_agent.py"

if [ ! -f "$AGENT_PATH" ]; then
    AGENT_PATH="$HOME/tb_agent.py"
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
User=$USER
WorkingDirectory=$HOME

[Install]
WantedBy=multi-user.target
EOF

    sudo systemctl daemon-reload
    echo "  Service created at $SERVICE_FILE"
    echo "  Note: configure TB_HOST and TB_TOKEN in tb_agent.py before enabling."
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
echo "    NODE_ID  = 'pi'"
echo ""
echo "  To run manually:"
echo "    source ~/pienv/bin/activate"
echo "    python3 tb_agent.py"
echo ""
echo "  To enable auto-start on boot:"
echo "    sudo systemctl enable tb-agent"
echo "    sudo systemctl start tb-agent"
echo "======================================================"
