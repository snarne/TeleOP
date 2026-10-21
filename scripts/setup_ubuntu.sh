#!/usr/bin/env bash
# One-time setup of a Teleop Station PC (Ubuntu 22.04 / 24.04).
#
#   bash scripts/setup_ubuntu.sh            # everything
#   bash scripts/setup_ubuntu.sh --no-i2rt  # skip cloning the I2RT SDK
#
# What it does (each step is idempotent):
#   1. apt packages (python, ffmpeg, can-utils, build tools, node for the UI)
#   2. a Python venv in .venv with the station + I2RT SDK + LeRobot (export)
#   3. adds you to the dialout + video groups (serial ports, cameras)
#   4. udev rules: 1 ms USB latency for U2D2s, stable names for HGMs, CAN auto-up
#   5. passwordless sudo for `ip link set can*` only, so the UI can reset CAN buses
#   6. builds the web UI
#   7. optional systemd service (prints the command)
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WITH_I2RT=1
for a in "$@"; do [[ "$a" == "--no-i2rt" ]] && WITH_I2RT=0; done
say() { printf "\n\033[1;34m==> %s\033[0m\n" "$*"; }

say "1/7 apt packages"
sudo apt-get update -y
sudo apt-get install -y python3 python3-venv python3-dev build-essential git ffmpeg can-utils \
  v4l-utils libgl1 curl "linux-headers-$(uname -r)" || true
if ! command -v node >/dev/null || [[ "$(node -v | cut -d. -f1 | tr -d v)" -lt 18 ]]; then
  curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
  sudo apt-get install -y nodejs
fi

say "2/7 python environment (.venv)"
cd "$REPO"
python3 -m venv .venv
# shellcheck disable=SC1091
source .venv/bin/activate
pip install --upgrade pip wheel
pip install -e ".[dev,input]"
if [[ $WITH_I2RT -eq 1 ]]; then
  if [[ ! -d "$REPO/third_party/i2rt" ]]; then
    git clone https://github.com/i2rt-robotics/i2rt.git "$REPO/third_party/i2rt"
  fi
  pip install -e "$REPO/third_party/i2rt"
fi
pip install "lerobot[dataset]" || echo "  (LeRobot install failed: export disabled until it's installed)"

say "3/7 groups (dialout, video, input)"
sudo usermod -aG dialout,video,input "$USER"

say "4/7 udev rules"
sudo cp "$REPO/scripts/udev/99-teleop-station.rules" /etc/udev/rules.d/
sudo udevadm control --reload-rules && sudo udevadm trigger

say "5/7 sudo rule for CAN interfaces (ip link only)"
SUDOERS=/etc/sudoers.d/teleop-station-can
echo "$USER ALL=(root) NOPASSWD: /usr/sbin/ip link set can* up type can bitrate 1000000, /usr/sbin/ip link set can* down, /sbin/ip link set can* up type can bitrate 1000000, /sbin/ip link set can* down" \
  | sudo tee "$SUDOERS" >/dev/null
sudo chmod 440 "$SUDOERS"
sudo visudo -cf "$SUDOERS"

say "6/7 web UI"
(cd "$REPO/ui" && npm ci && npm run build)

say "7/7 done"
cat <<EOF

  Next steps
  ----------
  * Log out and back in (group membership).
  * Give the CAN adapters persistent names:  scripts/udev/README.md
  * Edit config/station.yaml (every CHANGE_ME), then run:   .venv/bin/station doctor
  * Start the station:                                        .venv/bin/station serve
    and open http://localhost:8000
  * Optional: start on boot
      sudo cp scripts/systemd/teleop-station.service /etc/systemd/system/
      sudo sed -i "s|__USER__|$USER|; s|__REPO__|$REPO|" /etc/systemd/system/teleop-station.service
      sudo systemctl enable --now teleop-station
EOF
