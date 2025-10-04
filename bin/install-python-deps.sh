#!/bin/bash

set -e

/srv/venv/bin/pip install -U pip | grep -v "^Requirement already satisfied" || true
/srv/venv/bin/pip install -Ur /srv/app/requirements.txt | grep -v "^Requirement already satisfied" || true
