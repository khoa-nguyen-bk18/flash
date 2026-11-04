#!/usr/bin/env bash
# Shortcut to create release keystore
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$DIR/../flash" keystore create "$@"
