#!/bin/sh
# Fix ownership of the data volume, then drop root privileges (PUID/PGID configurable, NAS-friendly).
set -e

PUID="${PUID:-10001}"
PGID="${PGID:-10001}"
DATA_DIR="${SWITCH_MUSIC_DATA_DIR:-/data}"

if [ "$(id -u)" = "0" ]; then
    mkdir -p "$DATA_DIR"
    chown -R "$PUID:$PGID" "$DATA_DIR" 2>/dev/null || echo "warning: could not chown $DATA_DIR" >&2
    exec setpriv --reuid="$PUID" --regid="$PGID" --clear-groups "$@"
fi

exec "$@"
