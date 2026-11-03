#!/bin/bash

set -e

# Services can run as different users in one group. This lets them write to
# directories that this command creates, for example for uploaded files.
umask 002

# We use realpath because /srv/manage.py is a symlink. Without it, we would run
# manage.py from /srv, and its path calculations would start from there.
cd "$(dirname "$(realpath /srv/manage.py)")"
/srv/venv/bin/python manage.py "$@"
