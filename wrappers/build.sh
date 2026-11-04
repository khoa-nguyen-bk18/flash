#!/usr/bin/env bash
# Shortcut to build Android APK
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$DIR/../flash" build "$@"
