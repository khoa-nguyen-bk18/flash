#!/usr/bin/env bash
# Shortcut to clear app data and restart app immediately
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$DIR/../flash" clear-restart "$@"
