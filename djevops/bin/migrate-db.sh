#!/bin/bash

set -e

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"

su -c "${SCRIPT_DIR}/manage.sh migrate | grep -v 'INFO\|DEBUG'" - django
