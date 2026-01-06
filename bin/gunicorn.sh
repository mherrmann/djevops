#!/bin/bash

SOCKFILE=/var/run/django/$1.sock

# Create the run directory if it doesn't exist
RUNDIR=$(dirname $SOCKFILE)
test -d $RUNDIR || mkdir -p $RUNDIR

DJANGO_WSGI_MODULE=$(find . -name wsgi.py | sed 's|\.py$||' | sed 's|^\./||' | sed 's|/|.|')

exec gunicorn ${DJANGO_WSGI_MODULE}:application \
  --workers 1 \
  --threads 5 \
  --bind=unix:$SOCKFILE \
  --log-level=warning \
  --log-file=-
