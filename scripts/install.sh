#!/usr/bin/env bash
#
# One-shot installer for the iPhone Virtual Gamepad (PEDD §15).
#
# Run this ON THE RASPBERRY PI after copying the repo over, e.g.:
#   rsync -av --exclude .venv ./ dkim@raspberrypi:~/retropi_server/
#   ssh dkim@raspberrypi
#   cd ~/retropi_server && ./scripts/install.sh
#
# It is idempotent — safe to re-run. Override defaults with env vars:
#   RPC_USER=<user>            service account (default: the sudo-invoking user)
#   RPC_PORT=<port>            HTTP/WebSocket port (default: 8080)
#   RPC_PROFILE=<name>         controller profile (default: gameboy)
#   RPC_AUTOCONFIG_DIR=<dir>   RetroArch joypad dir (default: RetroPie's)
#
set -euo pipefail

SERVICE_NAME="iphone-controller"
DEFAULT_PORT=8080

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

log()  { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33mWARN:\033[0m %s\n' "$*" >&2; }
err()  { printf '\033[1;31mERROR:\033[0m %s\n' "$*" >&2; }

# This installer is Pi/Linux-specific (apt, systemd, uinput).
if [ "$(uname -s)" != "Linux" ]; then
  err "This installer targets the Raspberry Pi (Linux). uinput/systemd are unavailable here."
  exit 1
fi

# Re-run under sudo if needed (-E keeps any RPC_* overrides).
if [ "$(id -u)" -ne 0 ]; then
  log "Elevating with sudo…"
  exec sudo -E bash "$0" "$@"
fi

# --- resolve the service account ---------------------------------------------
RUN_USER="${RPC_USER:-${SUDO_USER:-}}"
if [ -z "$RUN_USER" ] || [ "$RUN_USER" = "root" ]; then
  RUN_USER="$(logname 2>/dev/null || true)"
fi
if [ -z "$RUN_USER" ] || [ "$RUN_USER" = "root" ]; then
  err "Could not determine a non-root service user. Re-run as: sudo RPC_USER=<you> $0"
  exit 1
fi
if ! id "$RUN_USER" >/dev/null 2>&1; then
  err "User '$RUN_USER' does not exist."
  exit 1
fi

PORT="${RPC_PORT:-$DEFAULT_PORT}"
PROFILE="${RPC_PROFILE:-gameboy}"
AUTOCONF_DIR="${RPC_AUTOCONFIG_DIR:-/opt/retropie/configs/all/retroarch-joypads}"
VENV="$REPO_DIR/.venv"
PY="$VENV/bin/python"
UV=""                                    # absolute path to uv, resolved by bootstrap_uv

log "Installing for user '$RUN_USER'"
log "  repo:     $REPO_DIR"
log "  port:     $PORT"
log "  profile:  $PROFILE"

as_user() { sudo -H -u "$RUN_USER" "$@"; }   # -H sets HOME so uv's cache lands in the user's home

# --- 1. system packages ------------------------------------------------------
install_packages() {
  log "Installing system packages (python, build tools, libudev)…"
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -y
  # uv replaces python3-venv/pip, so they're not needed; python3-dev + build-essential +
  # libudev-dev are still required to compile python-uinput. curl fetches the uv installer.
  # joystick (jstest) + evtest are diagnostics for confirming the virtual pad shows up and
  # reports the expected button/hat events (jstest /dev/input/jsX, evtest /dev/input/eventX).
  apt-get install -y python3 python3-dev build-essential libudev-dev curl ca-certificates \
    joystick evtest
}

# --- 2. uinput kernel module + permissions -----------------------------------
setup_uinput() {
  log "Configuring uinput (kernel module + device permissions)…"
  modprobe uinput || warn "modprobe uinput failed now; it will autoload on next boot."
  echo "uinput" > /etc/modules-load.d/uinput.conf

  # Give the 'input' group rw on /dev/uinput, applied even on static creation.
  cat > /etc/udev/rules.d/99-uinput.rules <<'EOF'
KERNEL=="uinput", SUBSYSTEM=="misc", MODE="0660", GROUP="input", OPTIONS+="static_node=uinput"
EOF

  usermod -aG input "$RUN_USER"
  udevadm control --reload-rules
  udevadm trigger || true
}

# --- 3. uv (Python package/venv manager) -------------------------------------
bootstrap_uv() {
  # uv builds and runs the environment. It bootstraps venvs itself instead of relying
  # on Debian's python3-venv/ensurepip — the machinery whose stale ".venv/bin/python3"
  # was the original failure. Prefer an existing uv; otherwise install the static binary
  # to /usr/local/bin, a stable path both this script and the systemd unit can reach.
  if command -v uv >/dev/null 2>&1; then
    UV="$(command -v uv)"
  elif [ -x /usr/local/bin/uv ]; then
    UV=/usr/local/bin/uv
  else
    log "Installing uv to /usr/local/bin…"
    curl -LsSf https://astral.sh/uv/install.sh \
      | env UV_INSTALL_DIR=/usr/local/bin INSTALLER_NO_MODIFY_PATH=1 sh
    UV=/usr/local/bin/uv
  fi
  log "  uv:       $("$UV" --version 2>/dev/null || echo "$UV")"
}

# --- 3b. python env + dependencies (via uv) ----------------------------------
setup_env() {
  log "Building the virtualenv and installing Python deps with uv…"
  # Stop any prior (possibly crash-looping) service first: it restarts every few seconds
  # and would keep writing into .venv (e.g. __pycache__) while we delete it, which makes
  # `rm -rf` race and fail with "Directory not empty". Safe if the unit doesn't exist yet.
  systemctl stop "$SERVICE_NAME" 2>/dev/null || true
  # Wipe any foreign/leftover .venv (e.g. one rsynced from the Mac) so uv builds clean.
  rm -rf "$VENV"
  # `uv sync` materialises .venv from uv.lock: --frozen = reproducible (no re-resolve),
  # --no-dev leaves pytest/httpx off the Pi. The interpreter is taken from .python-version;
  # uv fetches a managed CPython when the system one is too old (Bullseye ships 3.9, but the
  # code needs >=3.10). python-uinput is compiled against that interpreter; libudev is the
  # system lib. Run as the service user so it owns .venv (managed Python lands in its home).
  as_user "$UV" --project "$REPO_DIR" sync --frozen --no-dev
}

# --- 4. systemd service ------------------------------------------------------
install_service() {
  log "Installing + starting systemd service '$SERVICE_NAME'…"
  cat > "/etc/systemd/system/${SERVICE_NAME}.service" <<EOF
[Unit]
Description=iPhone Virtual Gamepad Controller Service
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$RUN_USER
SupplementaryGroups=input
WorkingDirectory=$REPO_DIR
# `uv run --no-sync` runs app.py in the already-built .venv without touching the
# network or re-resolving at boot (the env was synced at install time).
ExecStart=$UV run --no-sync app.py
Environment=RPC_PORT=$PORT
Environment=RPC_PROFILE=$PROFILE
Environment=RPC_AUTOCONFIG_DIR=$AUTOCONF_DIR
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

  systemctl daemon-reload
  systemctl enable "$SERVICE_NAME"
  systemctl restart "$SERVICE_NAME"
}

# --- 4b. reboot permission (sudoers) -----------------------------------------
setup_reboot_permission() {
  # The client's REBOOT button asks the server (running as $RUN_USER, non-root) to
  # power-cycle the Pi via `sudo -n systemctl reboot`. Grant exactly that one command
  # without a password — nothing broader. Disable the feature entirely by setting
  # RPC_ALLOW_REBOOT=0 on the service (see backend/config.py).
  local systemctl_path sudoers
  systemctl_path="$(command -v systemctl || echo /usr/bin/systemctl)"
  sudoers="/etc/sudoers.d/iphone-controller-reboot"
  log "Granting '$RUN_USER' NOPASSWD on '$systemctl_path reboot'…"
  cat > "$sudoers" <<EOF
$RUN_USER ALL=(root) NOPASSWD: $systemctl_path reboot
EOF
  chmod 0440 "$sudoers"
  # A malformed sudoers file can wedge sudo, so validate and back out if visudo rejects it.
  if ! visudo -cf "$sudoers" >/dev/null 2>&1; then
    err "sudoers validation failed for $sudoers; removing it (REBOOT button will no-op)."
    rm -f "$sudoers"
  fi
}

# --- 5. RetroArch autoconfig -------------------------------------------------
generate_autoconfig() {
  if [ -d "$AUTOCONF_DIR" ]; then
    log "Generating RetroArch autoconfig in $AUTOCONF_DIR…"
    as_user "$PY" "$REPO_DIR/scripts/generate_autoconfig.py" \
      --profile "$PROFILE" --dir "$AUTOCONF_DIR" \
      || warn "autoconfig not written (dir not owned by $RUN_USER?); the service also writes it on start."
  else
    warn "RetroArch joypad dir not found at $AUTOCONF_DIR — skipping."
    warn "If RetroPie lives elsewhere, re-run with RPC_AUTOCONFIG_DIR=<dir>."
  fi
}

# --- 5b. EmulationStation joystick mapping (es_input.cfg) ---------------------
generate_es_input() {
  # RetroArch autoconfig (above) covers in-game input; EmulationStation's launcher
  # reads its own es_input.cfg to navigate menus with a pad. A fresh image only maps
  # the keyboard, so we merge a joystick <inputConfig> for the virtual gamepad into
  # any existing es_input.cfg, leaving the keyboard entry intact. Idempotent.
  local guid_arg=()
  [ -n "${RPC_ES_DEVICE_GUID:-}" ] && guid_arg=(--guid "$RPC_ES_DEVICE_GUID")
  local found=0
  for cfg in \
    /opt/retropie/configs/all/emulationstation/es_input.cfg \
    "/home/$RUN_USER/.emulationstation/es_input.cfg"; do
    if [ -f "$cfg" ]; then
      log "Adding joystick mapping to EmulationStation input ($cfg)…"
      as_user "$PY" "$REPO_DIR/scripts/generate_es_input.py" \
        --profile "$PROFILE" --file "$cfg" "${guid_arg[@]}" \
        || warn "could not update $cfg (parse error or ownership?)."
      found=1
    fi
  done
  if [ "$found" -eq 0 ]; then
    warn "No EmulationStation es_input.cfg found — skipping joystick menu mapping."
    warn "Boot EmulationStation once (it writes es_input.cfg), then re-run this installer."
  fi
}

# --- 6. firewall (optional) --------------------------------------------------
configure_firewall() {
  if command -v ufw >/dev/null 2>&1 && ufw status 2>/dev/null | grep -q "Status: active"; then
    log "Opening port $PORT in ufw…"
    ufw allow "${PORT}/tcp" || warn "Could not add ufw rule."
  else
    log "No active ufw firewall detected; nothing to open."
  fi
}

# --- 7. summary --------------------------------------------------------------
summary() {
  local ip hostn active
  ip="$(hostname -I 2>/dev/null | awk '{print $1}')"
  hostn="$(hostname -s 2>/dev/null || hostname)"
  active="$(systemctl is-active "$SERVICE_NAME" 2>/dev/null || echo unknown)"

  echo
  log "Install complete."
  echo "  Service : ${SERVICE_NAME} (${active})"
  echo "  Connect : http://${ip:-<pi-ip>}:${PORT}    or    http://${hostn}.local:${PORT} or http://gamepad.local:${PORT}"
  echo "  QR code : sudo journalctl -u ${SERVICE_NAME} -b --no-pager | tail -n 40"
  echo "  Follow  : sudo journalctl -u ${SERVICE_NAME} -f"
  echo
  if [ ! -e /dev/uinput ]; then
    warn "/dev/uinput is not present yet — reboot the Pi so the uinput module loads, then it'll work."
  fi
  if [ "$active" != "active" ]; then
    warn "Service is not active. Inspect with: sudo journalctl -u ${SERVICE_NAME} -b --no-pager"
  fi
}

install_packages
setup_uinput
bootstrap_uv
setup_env
install_service
setup_reboot_permission
generate_autoconfig
generate_es_input
configure_firewall
summary
