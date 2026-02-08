#!/bin/bash

set -e

echo `date +%H:%M:%S`': Updating server...'

git -C /srv/app pull --rebase

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"

${SCRIPT_DIR}/install-python-deps.sh
${SCRIPT_DIR}/migrate-db.sh
${SCRIPT_DIR}/collect-static-files.sh

if supervisorctl status beat >/dev/null 2>&1; then
  supervisorctl restart beat
fi

if supervisorctl status worker >/dev/null 2>&1; then
  supervisorctl restart worker
fi

if supervisorctl status gunicorn >/dev/null 2>&1; then
  supervisorctl status gunicorn | sed "s/.*[pid ]\([0-9]\+\)\,.*/\1/" | xargs kill -HUP
fi

nginx -s reload

echo `date +%H:%M:%S`': Server update complete.'
