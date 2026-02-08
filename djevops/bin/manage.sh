#!/bin/bash

set -e

source /srv/venv/bin/activate
cd /srv/app
./manage.py "$@"
