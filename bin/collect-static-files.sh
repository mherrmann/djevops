#!/bin/bash

set -e

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"

# We in particular need the STATIC_ROOT setting:
source /home/django/.bashrc

${SCRIPT_DIR}/manage.sh collectstatic --noinput | grep -v "INFO\|DEBUG" > /dev/null
