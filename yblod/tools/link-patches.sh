#!/bin/sh
# Check (default) or repair (--fix) the patch layout. The patch files live in the owner
# folders yblod-engine/patches/<package>/ and yblod/patches/<package>/. LibreELEC applies
# patches from projects/Generic/patches/<package>/ (or the package's own patches folder,
# see target_dir), where each patch is a relative symlink to its owner copy. Patches are
# applied in file name order inside that folder, as if the files were stored there.
#
# The check exits non-zero when
#   - an owner patch has no link, or its link points anywhere else,
#   - a link has no owner patch, or points at nothing,
#   - a regular .patch or .diff file sits in a folder an owner folder feeds (a copy that
#     drifts from its owner, or a patch that was never moved to one),
#   - two owner folders have a patch of the same name for the same package.
#
# --fix creates and repairs links and removes dangling links and links without an owner
# patch. It never touches a regular file: move it into its owner folder by hand, then
# run --fix. Run the check before building (yblod/tools/build.sh does) and after merging
# LibreELEC.
#
# usage: yblod/tools/link-patches.sh [--fix]
set -eu

OWNERS="yblod-engine yblod"

usage() {
  echo "usage: yblod/tools/link-patches.sh [--fix]" >&2
  exit 2
}

fix=0
case "${1:-}" in
  "") ;;
  --fix) fix=1 ;;
  *) usage ;;
esac
[ $# -le 1 ] || usage

ROOT=$(cd "$(dirname "$0")/../.." && pwd)
cd "${ROOT}"
status=0

# owner/patches/<package> -> LibreELEC patch folder for that package
target_dir() {
  case "$1" in
    LibreELEC-settings) echo packages/mediacenter/LibreELEC-settings/patches ;;
    *) echo "projects/Generic/patches/$1" ;;
  esac
}

# "../" for every component of a folder below ${ROOT}, so that "$(updir "${dir}")<path>"
# is <path> (relative to ${ROOT}) seen from inside ${dir}
updir() {
  _rest=$1
  _up=
  while :; do
    _up="${_up}../"
    case "${_rest}" in
      */*) _rest=${_rest#*/} ;;
      *) break ;;
    esac
  done
  echo "${_up}"
}

problem() {
  echo "$*"
  status=1
}

# Owner patches and their links
fed=
for owner in ${OWNERS}; do
  for dir in "${owner}"/patches/*/; do
    [ -d "${dir}" ] || continue
    pkg=$(basename "${dir}")
    dest=$(target_dir "${pkg}")
    case " ${fed} " in
      *" ${pkg} "*) ;;
      *) fed="${fed} ${pkg}" ;;
    esac
    for patch in "${dir}"*.patch; do
      [ -f "${patch}" ] || continue
      name=$(basename "${patch}")
      for other in ${OWNERS}; do
        [ "${other}" = "${owner}" ] && break
        if [ -e "${other}/patches/${pkg}/${name}" ]; then
          problem "same patch in two owner folders: ${other}/patches/${pkg}/${name}" \
                  "and ${patch}"
        fi
      done
      link="${dest}/${name}"
      rel="$(updir "${dest}")${patch}"
      # a regular file in the link's place is reported with the other copies below
      if [ -e "${link}" ] && [ ! -L "${link}" ]; then
        continue
      fi
      if [ -L "${link}" ] && [ "$(readlink "${link}")" = "${rel}" ]; then
        continue
      fi
      if [ "${fix}" -eq 1 ]; then
        mkdir -p "${dest}"
        rm -f "${link}"
        ln -s "${rel}" "${link}"
        echo "linked ${link}"
      else
        problem "missing or wrong: ${link} -> ${rel}"
      fi
    done
  done
done

# What the folders LibreELEC reads hold besides those links
for pkg in ${fed}; do
  dest=$(target_dir "${pkg}")
  for file in "${dest}"/*.patch "${dest}"/*.diff; do
    if [ -L "${file}" ]; then
      [ -e "${file}" ] || continue # dangling: reported below
      name=$(basename "${file}")
      owned=0
      for owner in ${OWNERS}; do
        [ -f "${owner}/patches/${pkg}/${name}" ] && owned=1
      done
      [ "${owned}" -eq 1 ] && continue
      if [ "${fix}" -eq 1 ]; then
        rm -f "${file}"
        echo "removed link without owner patch ${file}"
      else
        problem "link without owner patch: ${file}"
      fi
    elif [ -f "${file}" ]; then
      name=$(basename "${file}")
      owned=0
      for owner in ${OWNERS}; do
        [ -f "${owner}/patches/${pkg}/${name}" ] && owned=1
      done
      if [ "${owned}" -eq 1 ]; then
        problem "regular file, copy of an owner patch (replace with a link): ${file}"
      else
        problem "regular file, no owner patch (move it to an owner folder): ${file}"
      fi
    fi
  done
done

# Dangling links anywhere LibreELEC looks (a patch was renamed or removed in its owner)
dangling=$(find projects packages -type l -name '*.patch' ! -exec test -e {} \; -print)
while IFS= read -r link; do
  [ -n "${link}" ] || continue
  if [ "${fix}" -eq 1 ]; then
    rm -f "${link}"
    echo "removed dangling ${link}"
  else
    problem "dangling: ${link}"
  fi
done <<EOF
${dangling}
EOF

if [ "${status}" -eq 0 ] && [ "${fix}" -eq 0 ]; then
  echo "patch links OK"
fi
exit "${status}"
