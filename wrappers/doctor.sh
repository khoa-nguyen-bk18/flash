#!/usr/bin/env bash
# Shortcut to run environment diagnostics
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$DIR/../flash" doctor "$@"
