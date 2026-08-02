#!/bin/bash

set -eo pipefail

SERVICE=$1
COMMAND=$2

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
