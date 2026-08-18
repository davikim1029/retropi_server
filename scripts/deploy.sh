#!/usr/bin/env bash
#
# Fast redeploy for an already-installed Pi.
#
# This syncs the local repo, refreshes the locked Python environment on the Pi,
# then restarts the long-running Python services so new backend code is loaded.
# Use scripts/install.sh and webplay/install-services.sh for fresh installs or
# service/unit/RetroArch config changes.
#
# Defaults match the current hardware setup:
#   RPC_DEPLOY_HOST=dkim@raspberrypi.tail571bc8.ts.net
#   RPC_DEPLOY_DIR=/home/dkim/GitHub/retropi_server
#   RPC_DEPLOY_SERVICES=iphone-controller,webplay
#   RPC_DEPLOY_CONNECT_TIMEOUT=10
#
# Examples:
#   scripts/deploy.sh
#   scripts/deploy.sh --sync-only
#   scripts/deploy.sh --restart-only
#   scripts/deploy.sh --interactive
#   RPC_DEPLOY_SERVICES=iphone-controller scripts/deploy.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

DEPLOY_HOST="${RPC_DEPLOY_HOST:-dkim@raspberrypi.tail571bc8.ts.net}"
DEPLOY_DIR="${RPC_DEPLOY_DIR:-/home/dkim/GitHub/retropi_server}"
SERVICES="${RPC_DEPLOY_SERVICES:-iphone-controller,webplay}"
SYNC_DEPS="${RPC_DEPLOY_SYNC_DEPS:-1}"
CONNECT_TIMEOUT="${RPC_DEPLOY_CONNECT_TIMEOUT:-10}"
BATCH_MODE="${RPC_DEPLOY_BATCH_MODE:-1}"
DO_SYNC=1
DO_RESTART=1

usage() {
  cat <<'USAGE'
Usage: scripts/deploy.sh [options]

Options:
  --sync-only       Copy files and sync deps, but do not restart services.
  --restart-only    Restart services without copying files or syncing deps.
  --no-deps         Skip remote `uv sync --frozen --no-dev`.
  --services LIST   Comma-separated services to restart.
  --interactive     Allow SSH prompts instead of failing fast.
  -h, --help        Show this help.

Environment:
  RPC_DEPLOY_HOST       SSH target. Default: dkim@raspberrypi.tail571bc8.ts.net
  RPC_DEPLOY_DIR        Remote repo path. Default: /home/dkim/GitHub/retropi_server
  RPC_DEPLOY_SERVICES   Services to restart. Default: iphone-controller,webplay
  RPC_DEPLOY_SYNC_DEPS  Set to 0 to skip remote uv sync.
  RPC_DEPLOY_CONNECT_TIMEOUT
                        SSH connect timeout in seconds. Default: 10
  RPC_DEPLOY_BATCH_MODE Set to 0 to allow SSH auth prompts.
USAGE
}

log() { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33mWARN:\033[0m %s\n' "$*" >&2; }
err() { printf '\033[1;31mERROR:\033[0m %s\n' "$*" >&2; }

quote_remote() {
  printf "'"
  printf "%s" "$1" | sed "s/'/'\\\\''/g"
  printf "'"
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --sync-only)
      DO_RESTART=0
      ;;
    --restart-only)
      DO_SYNC=0
      SYNC_DEPS=0
      ;;
    --no-deps)
      SYNC_DEPS=0
      ;;
    --services)
      shift
      if [ "$#" -eq 0 ]; then
        err "--services requires a value"
        exit 2
      fi
      SERVICES="$1"
      ;;
    --interactive)
      BATCH_MODE=0
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      err "Unknown option: $1"
      usage >&2
      exit 2
      ;;
  esac
  shift
done

if [ "$DO_SYNC" -eq 0 ] && [ "$DO_RESTART" -eq 0 ]; then
  err "--sync-only and --restart-only cannot be used together"
  exit 2
fi

SSH_OPTS=(
  -o "ConnectTimeout=$CONNECT_TIMEOUT"
  -o ConnectionAttempts=1
  -o ServerAliveInterval=5
  -o ServerAliveCountMax=2
)
if [ "$BATCH_MODE" != "0" ]; then
  SSH_OPTS+=(-o BatchMode=yes)
fi

RSYNC_RSH="ssh -o ConnectTimeout=$CONNECT_TIMEOUT -o ConnectionAttempts=1 -o ServerAliveInterval=5 -o ServerAliveCountMax=2"
if [ "$BATCH_MODE" != "0" ]; then
  RSYNC_RSH="$RSYNC_RSH -o BatchMode=yes"
fi

ssh_remote() {
  ssh "${SSH_OPTS[@]}" "$DEPLOY_HOST" "$@"
}

sync_repo() {
  log "Ensuring remote directory exists: $DEPLOY_HOST:$DEPLOY_DIR"
  if ! ssh_remote "mkdir -p $(quote_remote "$DEPLOY_DIR")"; then
    err "Could not reach $DEPLOY_HOST over SSH."
    err "Try: ssh $DEPLOY_HOST"
    err "If first-time SSH auth is expected, run: scripts/deploy.sh --interactive"
    exit 1
  fi

  log "Syncing repo to $DEPLOY_HOST:$DEPLOY_DIR"
  rsync -av \
    -e "$RSYNC_RSH" \
    --exclude .venv \
    --exclude __pycache__ \
    --exclude .git \
    --exclude .pytest_cache \
    --exclude .DS_Store \
    --exclude 'webplay/mediamtx/mediamtx' \
    "$REPO_DIR/" "$DEPLOY_HOST:$DEPLOY_DIR/"
}

run_remote_finish() {
  local q_dir q_services q_sync_deps q_restart
  q_dir="$(quote_remote "$DEPLOY_DIR")"
  q_services="$(quote_remote "$SERVICES")"
  q_sync_deps="$(quote_remote "$SYNC_DEPS")"
  q_restart="$(quote_remote "$DO_RESTART")"

  ssh_remote "bash -s -- $q_dir $q_services $q_sync_deps $q_restart" <<'REMOTE'
set -euo pipefail

DEPLOY_DIR="$1"
SERVICES_RAW="$2"
SYNC_DEPS="$3"
DO_RESTART="$4"

log() { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33mWARN:\033[0m %s\n' "$*" >&2; }

cd "$DEPLOY_DIR"

INSTALLED_UNITS=()
if [ "$DO_RESTART" = "1" ]; then
  for svc in ${SERVICES_RAW//,/ }; do
    [ -n "$svc" ] || continue
    case "$svc" in
      *.service) unit="$svc" ;;
      *) unit="$svc.service" ;;
    esac

    if systemctl cat "$unit" >/dev/null 2>&1; then
      INSTALLED_UNITS+=("$unit")
    else
      warn "Skipping $unit because it is not installed"
    fi
  done
fi

STOPPED_FOR_DEPS=0
restore_stopped_services() {
  if [ "$STOPPED_FOR_DEPS" = "1" ] && [ "${#INSTALLED_UNITS[@]}" -gt 0 ]; then
    warn "Deploy did not finish cleanly; starting stopped services again"
    sudo -n systemctl start "${INSTALLED_UNITS[@]}" || true
  fi
}
trap restore_stopped_services ERR

if [ "$SYNC_DEPS" = "1" ]; then
  if [ "$DO_RESTART" = "1" ] && [ "${#INSTALLED_UNITS[@]}" -gt 0 ]; then
    log "Stopping services before dependency sync"
    sudo -n systemctl stop "${INSTALLED_UNITS[@]}"
    STOPPED_FOR_DEPS=1
  fi

  if command -v uv >/dev/null 2>&1; then
    UV="$(command -v uv)"
  elif [ -x /usr/local/bin/uv ]; then
    UV=/usr/local/bin/uv
  else
    warn "uv not found; skipping dependency sync"
    UV=""
  fi

  if [ -n "$UV" ]; then
    log "Syncing Python deps from uv.lock"
    "$UV" --project "$DEPLOY_DIR" sync --frozen --no-dev
  fi
fi

if [ "$DO_RESTART" = "1" ]; then
  if [ "${#INSTALLED_UNITS[@]}" -eq 0 ]; then
    warn "No installed services matched: $SERVICES_RAW"
  else
    log "Starting services with deployed code"
    sudo -n systemctl restart "${INSTALLED_UNITS[@]}"
    STOPPED_FOR_DEPS=0

    for unit in "${INSTALLED_UNITS[@]}"; do
      active="$(systemctl is-active "$unit" 2>/dev/null || true)"
      printf '  %s: %s\n' "$unit" "${active:-unknown}"
      if [ "$active" != "active" ]; then
        systemctl --no-pager --plain status "$unit" | sed -n '1,12p' || true
        exit 1
      fi
    done
  fi
fi

trap - ERR
REMOTE
}

if [ "$DO_SYNC" -eq 1 ]; then
  sync_repo
fi

if [ "$SYNC_DEPS" = "1" ] || [ "$DO_RESTART" -eq 1 ]; then
  run_remote_finish
fi

log "Deploy complete"
