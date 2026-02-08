#!/bin/bash

set -eo pipefail

SERVICE=$1

DJANGO_PROJECT=$(find . -name wsgi.py | head -1 | xargs dirname | sed 's|^\./||')

exec celery -A $DJANGO_PROJECT worker -B \
  -s /var/run/django/$SERVICE-schedule \
  --pidfile /var/run/django/$SERVICE.pid \
  -l info
