#!/bin/bash

set -eo pipefail

SERVICE=$1
COMMAND=$2

# We use realpath because /srv/manage.py is a symlink. Without it, we would run
# Celery from /srv and search all of /srv for wsgi.py.
cd "$(dirname "$(realpath /srv/manage.py)")"

DJANGO_PROJECT=$(find . -name wsgi.py | head -1 | xargs dirname | sed 's|^\./||')

# Beat needs a path for its persisted schedule. Keep it in the tmpfs run dir
# instead of letting it default into the app directory.
SCHEDULE=
if [ "$COMMAND" = beat ]; then
  SCHEDULE="-s /var/run/djevops/$SERVICE-schedule"
fi

exec celery -A $DJANGO_PROJECT $COMMAND $SCHEDULE \
  --pidfile /var/run/djevops/$SERVICE-$COMMAND.pid \
  -l info
