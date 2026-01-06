#!/bin/bash

set -e

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"

/opt/djevops/bin/with-bashrc.sh ${SCRIPT_DIR}/manage.sh collectstatic --noinput | grep -v "INFO\|DEBUG" > /dev/null
