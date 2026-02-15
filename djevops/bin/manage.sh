#!/bin/bash

set -e

cd /srv/app
/srv/venv/bin/python manage.py "$@"
