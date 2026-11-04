#!/usr/bin/env bash
# Shortcut to open interactive ADB Quick Operations popup or run quick actions
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$DIR/../flash" action "$@"
