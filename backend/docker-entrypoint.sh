#!/bin/sh
set -eu

if [ "$(id -u)" = "0" ]; then
  upload_dir="${UPLOAD_DIR:-/app/uploads}"
  case "$upload_dir" in
    /*) ;;
    *) upload_dir="/app/$upload_dir" ;;
  esac
  mkdir -p "$upload_dir"
  chown -R appuser:appuser "$upload_dir"
  exec setpriv --reuid=10001 --regid=10001 --init-groups "$@"
fi

exec "$@"
