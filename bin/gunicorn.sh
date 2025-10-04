#!/bin/bash

NAME="gunicorn"

SOCKFILE=/var/run/django/gunicorn.sock

echo "Starting $NAME as `whoami`"

# Create the run directory if it doesn't exist
RUNDIR=$(dirname $SOCKFILE)
test -d $RUNDIR || mkdir -p $RUNDIR

DJANGO_WSGI_MODULE=$(find . -name wsgi.py | sed 's|\.py$||' | sed 's|^\./||' | sed 's|/|.|')

exec gunicorn ${DJANGO_WSGI_MODULE}:application \
  --name $NAME \
  --workers 1 \
  --threads 5 \
  --user=$USER --group=django \
  --bind=unix:$SOCKFILE \
  --log-level=warning \
  --log-file=-
