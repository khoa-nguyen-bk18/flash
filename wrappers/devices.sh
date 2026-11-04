#!/usr/bin/env bash
# Shortcut to list or watch connected Android devices
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$DIR/../flash" devices "$@"
