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
#   RPC_VIDEO_ENABLED=1        opt in to live "stream mode": apt-installs ffmpeg, grants
#                              the kmsgrab capability, wires RPC_VIDEO_* into the unit
#                              (also honors RPC_VIDEO_CAPTURE/FPS/WIDTH/DRI_DEVICE/FFMPEG_CMD)
#
set -euo pipefail

SERVICE_NAME="iphone-controller"
MDNS_ALIAS_SERVICE="gamepad-mdns-alias"
MDNS_ALIAS_HOST="gamepad.local"     # keep in sync with backend/discovery/network.py
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

# Optional live-video "stream mode" is opt-in (off by default): a default install grants
# no extra privileges. Enable with RPC_VIDEO_ENABLED=1, which apt-installs ffmpeg, grants
# the kmsgrab capability, and wires RPC_VIDEO_* into the unit.
case "${RPC_VIDEO_ENABLED:-}" in 1|true|yes|TRUE|YES) VIDEO_ON=1;; *) VIDEO_ON=0;; esac
VIDEO_ENV_LINES=""

log "Installing for user '$RUN_USER'"
log "  repo:     $REPO_DIR"
log "  port:     $PORT"
log "  profile:  $PROFILE"
log "  video:    $([ "$VIDEO_ON" = 1 ] && echo "enabled (${RPC_VIDEO_CAPTURE:-kmsgrab})" || echo disabled)"

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
  # avahi-utils provides avahi-publish, used to advertise the gamepad.local mDNS alias
  # (avahi-daemon, which answers <hostname>.local, ships preinstalled on Raspberry Pi OS).
  apt-get install -y python3 python3-dev build-essential libudev-dev curl ca-certificates \
    joystick evtest avahi-utils
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

# --- 2b. live video / stream mode (opt-in) -----------------------------------
setup_video() {
  if [ "$VIDEO_ON" != "1" ]; then
    log "Live video disabled (set RPC_VIDEO_ENABLED=1 to enable stream mode)."
    return 0
  fi
  log "Enabling live video (stream mode)…"
  export DEBIAN_FRONTEND=noninteractive
  # ffmpeg does the capture+MJPEG encode; libcap2-bin provides setcap.
  apt-get install -y ffmpeg libcap2-bin
  # The default 'kmsgrab' capture needs CAP_SYS_ADMIN, but the service runs non-root.
  # Grant the capability on the ffmpeg binary — narrow + opt-in, in the same spirit as
  # the reboot sudoers rule. (kmsgrab maps the buffer already scanned out to HDMI
  # read-only, so the TV is unaffected.) Also add the user to video/render so it can
  # open /dev/dri for the grab. Note: this cap applies to all ffmpeg invocations — fine
  # for a single-purpose appliance; use RPC_VIDEO_CAPTURE=fbdev to avoid it for testing.
  local ff
  ff="$(readlink -f "$(command -v ffmpeg 2>/dev/null)" 2>/dev/null || true)"
  if [ -n "$ff" ] && command -v setcap >/dev/null 2>&1; then
    log "  granting cap_sys_admin on $ff (for kmsgrab)…"
    setcap cap_sys_admin+ep "$ff" || warn "setcap failed; kmsgrab may need RPC_VIDEO_CAPTURE=fbdev."
  else
    warn "ffmpeg/setcap missing; cannot grant the kmsgrab capability."
  fi
  usermod -aG video,render "$RUN_USER" || warn "could not add $RUN_USER to video/render groups."
}

# Build the Environment= lines for the unit when video is on. Forwards RPC_VIDEO_* that
# the operator set at install time so on-Pi tuning (which /dev/dri card, fps, the
# RPC_VIDEO_FFMPEG_CMD override) sticks without hand-editing the unit.
build_video_env() {
  VIDEO_ENV_LINES=""
  [ "$VIDEO_ON" = "1" ] || return 0
  VIDEO_ENV_LINES="Environment=RPC_VIDEO_ENABLED=1"
  local v
  for v in RPC_VIDEO_CAPTURE RPC_VIDEO_FPS RPC_VIDEO_WIDTH RPC_VIDEO_QUALITY \
           RPC_VIDEO_DRI_DEVICE RPC_VIDEO_FB_DEVICE RPC_VIDEO_FFMPEG_CMD; do
    if [ -n "${!v:-}" ]; then
      # Quote the value so commands with spaces (RPC_VIDEO_FFMPEG_CMD) survive systemd parsing.
      VIDEO_ENV_LINES+=$'\n'"Environment=\"$v=${!v}\""
    fi
  done
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
  build_video_env
  # Give the service the video/render groups too when streaming is on, so the ffmpeg
  # child can open /dev/dri for the KMS grab.
  local supp_groups="input"
  [ "$VIDEO_ON" = "1" ] && supp_groups="input video render"
  cat > "/etc/systemd/system/${SERVICE_NAME}.service" <<EOF
[Unit]
Description=iPhone Virtual Gamepad Controller Service
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$RUN_USER
SupplementaryGroups=$supp_groups
WorkingDirectory=$REPO_DIR
# `uv run --no-sync` runs app.py in the already-built .venv without touching the
# network or re-resolving at boot (the env was synced at install time).
ExecStart=$UV run --no-sync app.py
Environment=RPC_PORT=$PORT
Environment=RPC_PROFILE=$PROFILE
Environment=RPC_AUTOCONFIG_DIR=$AUTOCONF_DIR
${VIDEO_ENV_LINES}
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

# --- 4c. mDNS alias (gamepad.local) ------------------------------------------
setup_mdns_alias() {
  # The Pi already answers to <hostname>.local because avahi-daemon advertises its own
  # hostname. To ALSO answer to the friendly gamepad.local URL (printed at startup), we
  # publish an extra mDNS A-record alias with avahi-publish. avahi-publish runs in the
  # foreground and holds the record live until it exits, so it maps cleanly onto a
  # Type=simple unit: stopping the unit withdraws the name, restarting re-publishes it.
  #
  # The LAN IP is resolved at *start time* from `hostname -I`, so a reboot is self-correcting:
  # the enabled unit comes back up and re-publishes whatever IP DHCP just handed out. The unit
  # waits for an IP to exist before publishing, which closes the boot race where it would
  # otherwise start before the lease arrives. A live IP change *without* a reboot is the only
  # case needing a manual `sudo systemctl restart ${MDNS_ALIAS_SERVICE}`.
  #
  # Idempotent: re-running overwrites the unit, `enable` is a no-op if already enabled, and
  # `restart` swaps in a fresh publisher (briefly releasing then re-claiming the name, so no
  # duplicate/`gamepad-2.local` entries pile up).
  if ! command -v avahi-publish >/dev/null 2>&1; then
    warn "avahi-publish not found (avahi-utils) — skipping the ${MDNS_ALIAS_HOST} alias."
    warn "Install it with: sudo apt-get install -y avahi-utils, then re-run this installer."
    return
  fi
  local avahi_publish
  avahi_publish="$(command -v avahi-publish)"
  log "Publishing mDNS alias '${MDNS_ALIAS_HOST}' -> this Pi's LAN IP…"
  # Heredoc is unquoted so ${avahi_publish}/${MDNS_ALIAS_HOST} expand now, but the
  # \$(hostname …) substitution is escaped so it runs at service start, not install time.
  cat > "/etc/systemd/system/${MDNS_ALIAS_SERVICE}.service" <<EOF
[Unit]
Description=Publish ${MDNS_ALIAS_HOST} as an mDNS alias for the iPhone Virtual Gamepad
After=network-online.target avahi-daemon.service
Wants=network-online.target avahi-daemon.service

[Service]
Type=simple
# -a publishes an address (A) record; -R skips the reverse (PTR) entry so it can't clash
# with the host's own reverse record; -f retries instead of failing if avahi-daemon isn't
# ready yet. The loop blocks until 'hostname -I' yields an IP (handles the post-boot race
# before DHCP assigns one), then publishes the Pi's first address.
ExecStart=/bin/sh -c 'ip=""; while [ -z "\$ip" ]; do ip=\$(hostname -I | cut -d" " -f1); [ -z "\$ip" ] && sleep 1; done; exec ${avahi_publish} -a -R -f ${MDNS_ALIAS_HOST} "\$ip"'
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

  systemctl daemon-reload
  systemctl enable "$MDNS_ALIAS_SERVICE"
  systemctl restart "$MDNS_ALIAS_SERVICE"
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
  local ip hostn active alias_active
  ip="$(hostname -I 2>/dev/null | awk '{print $1}')"
  hostn="$(hostname -s 2>/dev/null || hostname)"
  active="$(systemctl is-active "$SERVICE_NAME" 2>/dev/null || echo unknown)"
  alias_active="$(systemctl is-active "$MDNS_ALIAS_SERVICE" 2>/dev/null || echo unknown)"

  echo
  log "Install complete."
  echo "  Service : ${SERVICE_NAME} (${active})"
  echo "  mDNS    : ${MDNS_ALIAS_SERVICE} (${alias_active}) — advertises ${MDNS_ALIAS_HOST}"
  echo "  Connect : http://${ip:-<pi-ip>}:${PORT}    or    http://${hostn}.local:${PORT} or http://${MDNS_ALIAS_HOST}:${PORT}"
  if [ "$VIDEO_ON" = "1" ]; then
    echo "  Video   : stream mode ON — tap 📺 in the browser, or check ${ip:-<pi-ip>}:${PORT}/video/status"
    echo "            tune capture on hardware via RPC_VIDEO_FFMPEG_CMD / RPC_VIDEO_DRI_DEVICE (see CLAUDE.md)"
  fi
  echo "  QR code : sudo journalctl -u ${SERVICE_NAME} -b --no-pager | tail -n 40"
  echo "  Follow  : sudo journalctl -u ${SERVICE_NAME} -f"
  echo
  if [ ! -e /dev/uinput ]; then
    warn "/dev/uinput is not present yet — reboot the Pi so the uinput module loads, then it'll work."
  fi
  if [ "$active" != "active" ]; then
    warn "Service is not active. Inspect with: sudo journalctl -u ${SERVICE_NAME} -b --no-pager"
  fi
  if [ "$alias_active" != "active" ]; then
    warn "${MDNS_ALIAS_HOST} alias is not active — clients can still use the IP / ${hostn}.local URLs."
    warn "Inspect with: sudo journalctl -u ${MDNS_ALIAS_SERVICE} -b --no-pager"
  fi
}

install_packages
setup_uinput
setup_video
bootstrap_uv
setup_env
install_service
setup_reboot_permission
setup_mdns_alias
generate_autoconfig
generate_es_input
configure_firewall
summary
