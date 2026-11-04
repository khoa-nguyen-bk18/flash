#!/usr/bin/env bash
# Shortcut to stream colored Logcat
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$DIR/../flash" logcat "$@"
