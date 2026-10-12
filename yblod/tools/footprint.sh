#!/bin/sh
# List every file YBLOD adds or changes outside yblod-engine/ and yblod/, relative to an
# upstream LibreELEC commit. Keep this list short: it is what a LibreELEC resync must review.
#
# usage: yblod/tools/footprint.sh [upstream-ref]
#   default upstream-ref: the LibreELEC master commit of the last resync merge
set -eu
cd "$(dirname "$0")/../.."
base=${1:-cd5ed44f054deff79f50fc748995d8e77942ce6b}
git diff --name-status "$base" -- . ':!yblod-engine' ':!yblod' |
  awk '{ s = ($1 == "M") ? "modified upstream" : ($1 == "D") ? "deleted upstream" : "added"; printf "%-18s %s\n", s, $NF }' |
  sort
