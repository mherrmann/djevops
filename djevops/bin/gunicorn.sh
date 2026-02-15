#!/bin/bash

set -eo pipefail

SOCKFILE=/var/run/djevops/$1.sock

# Create the run directory if it doesn't exist
RUNDIR=$(dirname $SOCKFILE)
test -d $RUNDIR || mkdir -p $RUNDIR

# Set the number of workers to the recommended value of 2 * num_cores + 1.
WORKERS=$(( 2 * $(nproc) + 1 ))

DJANGO_WSGI_MODULE=$(find . -name wsgi.py | sed 's|\.py$||' | sed 's|^\./||' | sed 's|/|.|')

exec gunicorn ${DJANGO_WSGI_MODULE}:application \
  --workers $WORKERS \
  --bind=unix:$SOCKFILE \
  --log-level=warning \
  --log-file=-
