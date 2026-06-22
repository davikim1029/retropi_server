#!/usr/bin/env bash
# Reversibly swap what tty1 autologin launches: EmulationStation <-> the spike
# runner. Edits the RetroPie ES hook block in ~/.bash_profile, keeping a backup.
#
#   spike/tty1.sh enable /home/dkim/RetroPie/roms/gba/<Game>.gba [gba|gbc]
#   spike/tty1.sh restore
#
# After enable: `sudo reboot` — tty1 boots into the spike runner (RetroArch +
# recording) instead of ES. After restore: `sudo reboot` — ES is back.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROFILE="$HOME/.bash_profile"
BACKUP="$HOME/.bash_profile.pre-spike"
BEGIN="# >>> rpc-spike >>>"
END="# <<< rpc-spike <<<"
RUNNER="$SCRIPT_DIR/spike-runner.sh"

strip_block() {  # remove any existing rpc-spike block from $PROFILE
  [ -f "$PROFILE" ] || return 0
  sed -i "/$BEGIN/,/$END/d" "$PROFILE"
}

case "${1:-}" in
  enable)
    ROM="${2:?usage: tty1.sh enable <abs-rom-path> [gba|gbc]}"
    SYS="${3:-gba}"
    [ -f "$BACKUP" ] || cp "$PROFILE" "$BACKUP"
    # Neutralize the stock ES autostart line, then append our guarded block.
    sed -i 's/^\([[:space:]]*\)emulationstation\b/\1: # emulationstation (rpc-spike disabled)/' "$PROFILE" || true
    strip_block
    cat >> "$PROFILE" <<EOF
$BEGIN
if [ -z "\$SSH_CONNECTION" ] && [ "\$(tty)" = "/dev/tty1" ]; then
  export RPC_SPIKE_SYS="$SYS"
  export RPC_SPIKE_ROM="$ROM"
  bash "$RUNNER"
fi
$END
EOF
    echo "tty1 -> spike runner ($SYS: $ROM). Now: sudo reboot"
    ;;
  webplay)
    # Point tty1 at the webplay fork runner (idle-launch: no hardcoded ROM).
    WRUNNER="$(cd "$SCRIPT_DIR/.." && pwd)/webplay/runner.sh"
    [ -f "$BACKUP" ] || cp "$PROFILE" "$BACKUP"
    sed -i 's/^\([[:space:]]*\)emulationstation\b/\1: # emulationstation (rpc-spike disabled)/' "$PROFILE" || true
    strip_block
    cat >> "$PROFILE" <<EOF
$BEGIN
if [ -z "\$SSH_CONNECTION" ] && [ "\$(tty)" = "/dev/tty1" ]; then
  bash "$WRUNNER"
fi
$END
EOF
    echo "tty1 -> webplay runner. Now: sudo reboot"
    ;;
  restore)
    strip_block
    if [ -f "$BACKUP" ]; then
      cp "$BACKUP" "$PROFILE"
      echo "Restored ~/.bash_profile from backup. Now: sudo reboot"
    else
      echo "No backup found; removed rpc-spike block. Verify ES line in $PROFILE, then reboot."
    fi
    ;;
  *)
    echo "usage: tty1.sh enable <abs-rom-path> [gba|gbc] | webplay | restore" >&2
    exit 2
    ;;
esac
