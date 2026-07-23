#!/bin/sh
set -eu

# The migration credential and role-creation passwords are pre-deploy only. Railway
# invokes the same image for pre-deploy and runtime, so strip them specifically from
# the Uvicorn process while leaving them available to the provisioning command.
case "$*" in
  *uvicorn*app.main:app*)
    case "$*" in
      *provision_runtime_role*) ;;
      *) unset MIGRATION_DATABASE_URL RUNTIME_DB_PASSWORD AGENT_DB_PASSWORD ;;
    esac
    ;;
esac

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
