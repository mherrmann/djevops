#!/bin/bash

set -e

# We use realpath because /srv/manage.py is a symlink. Without it, we would run
# manage.py from /srv, and its path calculations would start from there.
cd "$(dirname "$(realpath /srv/manage.py)")"
/srv/venv/bin/python manage.py "$@"
