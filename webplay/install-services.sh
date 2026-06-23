#!/usr/bin/env bash
# Reproducible webplay-appliance install: deps + MediaMTX + the RetroArch config the
# features rely on + systemd services + the tty1 launcher runner. Idempotent.
#
# Full setup on a fresh Pi (run on the Pi, in the repo):
#   1. ./scripts/install.sh            # base: uv, iphone-controller (:8080), uinput, autoconfig, firewall
#   2. bash webplay/install-services.sh   # this layer (MediaMTX + webplay + RetroArch cfg + tty1 runner)
#   3. sudo reboot                     # boots straight into the launcher
#
# Run as a FILE (not inline over ssh) so the pkill below matches stray nohup
# processes, not this script's own argv. Re-running is safe (idempotent).
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$SCRIPT_DIR/.." && pwd)"
USER_NAME="$(id -un)"
UV="$(command -v uv || echo /usr/local/bin/uv)"
MTX_VERSION="${RPC_MTX_VERSION:-v1.19.1}"
MTX_DIR="$SCRIPT_DIR/mediamtx"
RA_CFG="${RPC_RETROARCH_CFG:-/opt/retropie/configs/all/retroarch.cfg}"

echo "== webplay appliance install =="
echo "repo=$REPO user=$USER_NAME uv=$UV mediamtx=$MTX_VERSION"

# --- deps: publish.sh needs the ffmpeg binary (RetroArch records via libavcodec) ---
ensure_deps() {
  if ! command -v ffmpeg >/dev/null 2>&1; then
    echo "installing ffmpeg..."
    sudo apt-get update -qq && sudo apt-get install -y ffmpeg
  fi
  echo "ffmpeg: $(command -v ffmpeg)"
}

# --- MediaMTX (single Go binary; download if missing) ---
ensure_mediamtx() {
  if [ -x "$MTX_DIR/mediamtx" ]; then
    echo "MediaMTX present: $("$MTX_DIR/mediamtx" --version 2>/dev/null)"; return
  fi
  local arch asset; arch="$(uname -m)"
  case "$arch" in
    aarch64|arm64) asset="linux_arm64" ;;
    armv7l|armv6l) asset="linux_armv7" ;;
    x86_64)        asset="linux_amd64" ;;
    *) echo "unknown arch '$arch' — install MediaMTX into $MTX_DIR/ manually" >&2; return 1 ;;
  esac
  echo "downloading MediaMTX $MTX_VERSION ($asset)..."
  mkdir -p "$MTX_DIR"
  curl -fsSL -o "$MTX_DIR/mtx.tar.gz" \
    "https://github.com/bluenviron/mediamtx/releases/download/$MTX_VERSION/mediamtx_${MTX_VERSION}_${asset}.tar.gz"
  tar xzf "$MTX_DIR/mtx.tar.gz" -C "$MTX_DIR" && rm -f "$MTX_DIR/mtx.tar.gz"
  echo "MediaMTX installed: $("$MTX_DIR/mediamtx" --version 2>/dev/null)"
}

# --- RetroArch config the webplay features depend on (idempotent) ---
set_cfg() {  # key value -> "key = \"value\"" in RA_CFG (uncomment/replace or append)
  local key="$1" val="$2"
  if grep -qE "^[# ]*${key}[[:space:]]*=" "$RA_CFG"; then
    sed -i "s|^[# ]*${key}[[:space:]]*=.*|${key} = \"${val}\"|" "$RA_CFG"
  else
    echo "${key} = \"${val}\"" >> "$RA_CFG"
  fi
}
configure_retroarch() {
  if [ ! -f "$RA_CFG" ]; then echo "no $RA_CFG (RetroPie not installed?) — skipping RA config" >&2; return; fi
  set_cfg network_cmd_enable true   # ⏻ Power off uses RetroArch's UDP QUIT command
  set_cfg network_cmd_port 55355
  set_cfg autosave_interval 60      # flush in-game SRAM every 60s (survives a power-off, not just clean EXIT)
  echo "RetroArch cfg: $(grep -E '^(network_cmd_enable|network_cmd_port|autosave_interval)' "$RA_CFG" | tr '\n' ' ')"
  # GBA: lr-vba-next is much lighter than lr-mgba (full speed on a Pi 3B). Apply if available.
  local gba=/opt/retropie/configs/gba/emulators.cfg
  if [ -f "$gba" ] && [ -e /opt/retropie/libretrocores/lr-vba-next ] && grep -q '^default = "lr-mgba"' "$gba"; then
    sed -i 's|^default = "lr-mgba"|default = "lr-vba-next"|' "$gba"
    echo "GBA default -> lr-vba-next"
  fi
}

# --- systemd services (auto-start at boot, auto-restart on crash) ---
write_unit() { printf '%s\n' "$2" | sudo tee "/etc/systemd/system/$1" >/dev/null; echo "wrote /etc/systemd/system/$1"; }
install_services() {
  # retire any hand-started (nohup) instances so the services own the ports
  pkill -x mediamtx 2>/dev/null || true
  pkill -f "webplay_app.py" 2>/dev/null || true
  sleep 2
  write_unit mediamtx.service "[Unit]
Description=MediaMTX (WebRTC relay for webplay)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$USER_NAME
WorkingDirectory=$MTX_DIR
ExecStart=$MTX_DIR/mediamtx
Restart=always
RestartSec=2

[Install]
WantedBy=multi-user.target"

  write_unit webplay.service "[Unit]
Description=webplay launcher + WebRTC play app (:8091)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$USER_NAME
WorkingDirectory=$REPO
ExecStart=$UV run --no-sync webplay_app.py
Restart=always
RestartSec=2
Environment=RPC_LOG_LEVEL=warning

[Install]
WantedBy=multi-user.target"

  sudo systemctl daemon-reload
  sudo systemctl enable --now mediamtx.service webplay.service
}

# 'config' re-applies deps + MediaMTX + RetroArch cfg only (no service restart — safe
# while a game is running). 'full' (default) also (re)installs services + the tty1 hook.
case "${1:-full}" in
  config)
    ensure_deps; ensure_mediamtx; configure_retroarch
    echo "config applied (services/tty1 untouched)."
    ;;
  full)
    ensure_deps; ensure_mediamtx; configure_retroarch; install_services
    bash "$SCRIPT_DIR/../spike/tty1.sh" webplay >/dev/null && echo "tty1 -> webplay runner"
    sleep 3
    echo "== status =="
    systemctl is-active mediamtx webplay | paste <(printf 'mediamtx\nwebplay\n') -
    echo "Done. 'sudo reboot' to start the launcher runner on tty1."
    ;;
  *) echo "usage: install-services.sh [full|config]" >&2; exit 2 ;;
esac
