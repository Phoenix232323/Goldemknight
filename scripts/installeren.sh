#!/usr/bin/env bash
# Installatiescript voor het GoldenKnight dashboard op Raspberry Pi OS (64-bit).
#
#   bash scripts/installeren.sh
#
# Het script maakt een virtuele omgeving aan, installeert de pakketten en
# zet - als je dat wilt - de systemd-service klaar.

set -euo pipefail

PROJECT_MAP="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_MAP"

echo "GoldenKnight dashboard installeren in: $PROJECT_MAP"
echo

if ! command -v python3 >/dev/null 2>&1; then
    echo "Python 3 is niet gevonden. Installeer het eerst:"
    echo "   sudo apt update && sudo apt install -y python3 python3-venv python3-pip"
    exit 1
fi

if [ ! -d .venv ]; then
    echo "-> Virtuele omgeving aanmaken (.venv)"
    python3 -m venv .venv
fi

echo "-> Pakketten installeren"
./.venv/bin/pip install --upgrade pip >/dev/null
./.venv/bin/pip install -r requirements.txt

if [ ! -f .env ]; then
    echo "-> .env aanmaken vanuit .env.example"
    cp .env.example .env
fi

mkdir -p instance
chmod 700 instance

echo
read -r -p "Sensorbibliotheken voor de Raspberry Pi installeren? (j/N) " antwoord
if [[ "${antwoord,,}" == "j" ]]; then
    echo "-> Systeempakketten voor I2C/SPI"
    sudo apt update
    sudo apt install -y python3-dev libgpiod2 i2c-tools
    ./.venv/bin/pip install -r requirements-hardware.txt
    echo
    echo "Vergeet niet I2C en SPI aan te zetten met:  sudo raspi-config"
    echo "   Interface Options -> I2C -> Yes"
    echo "   Interface Options -> SPI -> Yes"
fi

echo
read -r -p "Automatisch starten bij het opstarten van de Pi? (j/N) " service_antwoord
if [[ "${service_antwoord,,}" == "j" ]]; then
    TIJDELIJK="$(mktemp)"
    sed -e "s#/home/pi/Goldemknight#${PROJECT_MAP}#g" \
        -e "s#^User=pi#User=$(id -un)#" \
        -e "s#^Group=pi#Group=$(id -gn)#" \
        deploy/goldenknight.service > "$TIJDELIJK"
    sudo cp "$TIJDELIJK" /etc/systemd/system/goldenknight.service
    rm -f "$TIJDELIJK"
    sudo systemctl daemon-reload
    sudo systemctl enable --now goldenknight
    echo "-> Service gestart. Bekijk de status met: sudo systemctl status goldenknight"
fi

echo
echo "Klaar."
echo
echo "Handmatig starten kan met:"
echo "   ./.venv/bin/python run.py"
echo
echo "Daarna in de browser:  http://$(hostname -I 2>/dev/null | awk '{print $1}'):5000"
echo "Inloggen met de gegevens uit .env (standaard: admin / goldenknight)."
echo "Verander dat wachtwoord meteen bij Instellingen."
