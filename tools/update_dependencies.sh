#!/bin/sh
set -eu

DRY_RUN=1
ROOT=${1:-.}

usage() {
  echo "Usage: $0 [--apply] [root]" >&2
  exit 2
}

if [ "${1:-}" = "--apply" ]; then
  DRY_RUN=0
  ROOT=${2:-.}
elif [ "${1:-}" = "--dry-run" ]; then
  ROOT=${2:-.}
elif [ "${1:-}" != "" ] && [ "${1#-}" != "$1" ]; then
  usage
fi

run() {
  if [ "$DRY_RUN" -eq 1 ]; then
    printf '[dry-run]'
    printf ' %s' "$@"
    printf '\n'
  else
    printf '[update] %s\n' "$*"
    "$@"
  fi
}

find "$ROOT" -type d -name .git -prune -print | while IFS= read -r gitdir; do
  repo=${gitdir%/.git}
  printf '\nRepository: %s\n' "$repo"
  if [ -f "$repo/package.json" ] && command -v npm >/dev/null 2>&1; then
    if [ "$DRY_RUN" -eq 1 ]; then run npm outdated --prefix "$repo"; else run npm update --prefix "$repo"; fi
  fi
  if [ -f "$repo/requirements.txt" ] && command -v pip >/dev/null 2>&1; then
    run pip list --outdated --format=columns
    [ "$DRY_RUN" -eq 1 ] || run pip install -r "$repo/requirements.txt" --upgrade
  fi
  if [ -f "$repo/go.mod" ] && command -v go >/dev/null 2>&1; then
    if [ "$DRY_RUN" -eq 1 ]; then run go list -m -u all; else run go get -u ./...; run go mod tidy; fi
  fi
  if [ -f "$repo/Cargo.toml" ] && command -v cargo >/dev/null 2>&1; then
    if [ "$DRY_RUN" -eq 1 ]; then run cargo update --dry-run; else run cargo update; fi
  fi
done
