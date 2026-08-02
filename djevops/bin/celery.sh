#!/bin/bash

set -eo pipefail

SERVICE=$1
ROLE=$2

DJANGO_PROJECT=$(find . -name wsgi.py | head -1 | xargs dirname | sed 's|^\./||')

case $ROLE in
  worker)
    exec celery -A $DJANGO_PROJECT worker -l info
    ;;
  beat)
    SCHEDULE=/var/lib/djevops/$SERVICE-schedule
    # As of Python 3.13, shelve - which Beat stores its schedule in - is backed
    # by SQLite in WAL mode. Beat recovers from a corrupted schedule by deleting
    # it, but does not know about WAL's -wal and -shm companion files. A pair
    # left behind by an unclean exit then makes every subsequent start fail with
    # "locking protocol". Deleting them only discards when tasks last ran.
    rm -f $SCHEDULE-wal $SCHEDULE-shm
    exec celery -A $DJANGO_PROJECT beat -s $SCHEDULE -l info
    ;;
  *)
    echo "Unknown Celery role: $ROLE" >&2
    exit 1
    ;;
esac
