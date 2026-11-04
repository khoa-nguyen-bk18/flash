#!/usr/bin/env bash
# Shortcut to build, install, and run Android app on device
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$DIR/../flash" run "$@"
