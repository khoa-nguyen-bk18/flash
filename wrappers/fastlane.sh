#!/usr/bin/env bash
# Shortcut to run Fastlane lanes via bundle exec
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$DIR/../flash" fastlane "$@"
