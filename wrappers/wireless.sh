#!/usr/bin/env bash
# Shortcut to configure wireless debugging
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$DIR/../flash" wireless "$@"
