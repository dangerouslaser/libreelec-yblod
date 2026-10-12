#!/bin/sh
# Check (default) or create (--fix) the patch symlinks that wire yblod-engine/patches and
# yblod/patches into the folders LibreELEC applies patches from. Patch order is the file
# name order inside each LibreELEC folder, exactly as if the files were stored there.
#
# usage: yblod/tools/link-patches.sh [--fix]
set -eu
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
cd "$ROOT"
fix=0; [ "${1:-}" = "--fix" ] && fix=1
status=0

# owner/patches/<package> -> LibreELEC patch folder for that package
target_dir() {
  case "$1" in
    libplacebo) echo packages/addons/addon-depends/multimedia-tools-depends/libplacebo/patches ;;
    LibreELEC-settings) echo packages/mediacenter/LibreELEC-settings/patches ;;
    *) echo "projects/Generic/patches/$1" ;;
  esac
}

for owner in yblod-engine yblod; do
  for dir in "$owner"/patches/*/; do
    [ -d "$dir" ] || continue
    pkg=$(basename "$dir"); dest=$(target_dir "$pkg")
    for patch in "$dir"*.patch; do
      [ -f "$patch" ] || continue
      link="$dest/$(basename "$patch")"
      rel=$(python3 -c 'import os,sys;print(os.path.relpath(sys.argv[1],os.path.dirname(sys.argv[2])))' "$patch" "$link")
      if [ -L "$link" ] && [ "$(readlink "$link")" = "$rel" ]; then continue; fi
      if [ $fix -eq 1 ]; then
        mkdir -p "$dest"; rm -f "$link"; ln -s "$rel" "$link"; echo "linked $link"
      else
        echo "missing or wrong: $link -> $rel"; status=1
      fi
    done
  done
done

# Dangling links (a patch was renamed or removed in its owner folder)
for link in $(find projects/Generic/patches packages -type l -name '*.patch' 2>/dev/null); do
  if [ ! -e "$link" ]; then
    if [ $fix -eq 1 ]; then rm -f "$link"; echo "removed dangling $link"; else echo "dangling: $link"; status=1; fi
  fi
done
[ $status -eq 0 ] && [ $fix -eq 0 ] && echo "patch links OK"
exit $status
