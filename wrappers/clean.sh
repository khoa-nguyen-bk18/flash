#!/usr/bin/env bash
# Shortcut to clean project build artifacts
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$DIR/../flash" clean "$@"
