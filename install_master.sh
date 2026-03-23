#!/bin/bash
# install_master.sh
# ==================
# Installs all dependencies for the MAB scheduler master node (PC).
# Run this on the PC that hosts ThingsBoard and the scheduler.
#
# Usage:
#   chmod +x install_master.sh
#   ./install_master.sh

set -e  # exit on error

echo "======================================================"
echo " MAB Scheduler — Master Node Setup"
echo "======================================================"

# ── 1. System dependencies ─────────────────────────────────
echo ""
echo "[1/5] Installing system dependencies..."
sudo apt update -qq
sudo apt install -y \
    python3 python3-pip python3-venv \
    openjdk-17-jdk \
    postgresql postgresql-contrib \
    curl wget

# ── 2. ThingsBoard CE ──────────────────────────────────────
echo ""
echo "[2/5] Installing ThingsBoard CE..."

TB_VERSION="3.6.4"
TB_DEB="thingsboard-${TB_VERSION}.deb"
TB_URL="https://github.com/thingsboard/thingsboard/releases/download/v${TB_VERSION}/${TB_DEB}"

if systemctl is-active --quiet thingsboard 2>/dev/null; then
    echo "  ThingsBoard already running — skipping install."
else
    if [ ! -f "/tmp/${TB_DEB}" ]; then
        echo "  Downloading ThingsBoard ${TB_VERSION}..."
        wget -q --show-progress -O "/tmp/${TB_DEB}" "${TB_URL}"
    fi

    sudo dpkg -i "/tmp/${TB_DEB}"

    echo "  Configuring PostgreSQL..."
    sudo systemctl start postgresql
    sudo -u postgres psql -c "CREATE DATABASE thingsboard;" 2>/dev/null || true
    sudo -u postgres psql -c \
        "CREATE USER thingsboard WITH PASSWORD 'postgres';" 2>/dev/null || true
    sudo -u postgres psql -c \
        "GRANT ALL PRIVILEGES ON DATABASE thingsboard TO thingsboard;" 2>/dev/null || true

    echo "  Running ThingsBoard install script..."
    sudo /usr/share/thingsboard/bin/install/install.sh --loadDemo

    sudo systemctl enable thingsboard
    sudo systemctl start thingsboard

    echo "  Waiting for ThingsBoard to start (60s)..."
    sleep 60
fi

# ── 3. Python virtual environment ─────────────────────────
echo ""
echo "[3/5] Setting up Python virtual environment..."

VENV_DIR="$HOME/pcenv"

if [ -d "$VENV_DIR" ]; then
    echo "  Virtual environment already exists at $VENV_DIR"
else
    python3 -m venv "$VENV_DIR"
    echo "  Created virtual environment at $VENV_DIR"
fi

source "$VENV_DIR/bin/activate"

pip install --upgrade pip -q
pip install \
    paho-mqtt \
    psutil \
    numpy \
    requests \
    matplotlib \
    pandas

echo "  Packages installed in $VENV_DIR"
deactivate

# ── 4. Verify ThingsBoard ──────────────────────────────────
echo ""
echo "[4/5] Verifying ThingsBoard..."

if curl -s http://localhost:8080/api/noauth/activate | grep -q "html" 2>/dev/null; then
    echo "  ThingsBoard is reachable at http://localhost:8080"
else
    echo "  Warning: ThingsBoard not yet responding — may still be starting."
    echo "  Try: sudo systemctl status thingsboard"
fi

# ── 5. Summary ─────────────────────────────────────────────
echo ""
echo "[5/5] Done."
echo ""
echo "======================================================"
echo " Setup complete!"
echo "======================================================"
echo ""
echo "  ThingsBoard UI:   http://localhost:8080"
echo "  Default login:    tenant@thingsboard.org / tenant"
echo ""
echo "  To activate the Python environment:"
echo "    source ~/pcenv/bin/activate"
echo ""
echo "  To run the scheduler:"
echo "    source ~/pcenv/bin/activate"
echo "    python3 master_scheduler.py"
echo ""
echo "  To check ThingsBoard status:"
echo "    sudo systemctl status thingsboard"
echo "======================================================"
