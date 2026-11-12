#!/bin/bash
# SPDX-License-Identifier: GPL-2.0-only
#
# reboot-image.sh BOX NAME
#
# Boots the bench profile NAME that install-image.sh installed once more: a
# reboot of LibreELEC lands in big-fella (first in BootOrder), which is asked
# to boot LibreELEC next (BootNext, once). Nothing is written on the box.
# Stops if anything is playing in either system, or if the System partition
# holds another profile than NAME.

set -euo pipefail

[ $# -eq 2 ] || { sed -n '3,9p' "$0"; exit 2; }
BOX="$1"
NAME="$2"

LE_ENTRY="UEFI OS"
LE_SSH=(ssh -o BatchMode=yes -o ConnectTimeout=8 -o UserKnownHostsFile=/dev/null
        -o StrictHostKeyChecking=no -o LogLevel=ERROR "${BOX}")
BF_SSH=(ssh -o BatchMode=yes -o ConnectTimeout=8 "${BOX}")

die() {
  echo "reboot-image: $*" >&2
  exit 1
}

running() {
  "${LE_SSH[@]}" '. /etc/os-release; echo "${NAME}"' 2>/dev/null || true
}

wait_for() {
  local n
  for n in $(seq 1 40); do
    [ "$(running)" = "$1" ] && return 0
    sleep 6
  done
  die "the box did not come up as $1"
}

if [ "$(running)" = "LibreELEC" ]; then
  [ "$("${LE_SSH[@]}" cat /flash/bench-name)" = "${NAME}" ] ||
    die "the box runs another profile than ${NAME}"
  players=$("${LE_SSH[@]}" "curl -s -m 5 -u kodi:bench -H 'Content-Type: application/json' \
    -d '{\"jsonrpc\":\"2.0\",\"method\":\"Player.GetActivePlayers\",\"id\":1}' \
    http://127.0.0.1:8080/jsonrpc")
  [ "${players}" = '{"id":1,"jsonrpc":"2.0","result":[]}' ] ||
    die "Kodi is playing or does not answer (${players}): not rebooting"
  "${LE_SSH[@]}" reboot || true
  sleep 15
  wait_for "Arch Linux"
fi
[ "$(running)" = "Arch Linux" ] || die "the box runs neither big-fella nor LibreELEC"

IDLE='! pgrep -x mpv >/dev/null && ! grep -qs RUNNING /proc/asound/card*/pcm*p/sub*/status'
"${BF_SSH[@]}" "${IDLE}" || die "big-fella is playing something: not touching the box"
"${BF_SSH[@]}" "efibootmgr | grep -q '^BootOrder: 0000,' &&
  efibootmgr | grep -q '^Boot0005\* ${LE_ENTRY}' &&
  mkdir -p /mnt/lesys && { mountpoint -q /mnt/lesys || mount -o ro /dev/mmcblk0p1 /mnt/lesys; } &&
  name=\$(cat /mnt/lesys/bench-name) && umount /mnt/lesys && [ \"\${name}\" = '${NAME}' ]" ||
  die "the box is not set up as expected (boot entries, or the System partition is not ${NAME})"
"${BF_SSH[@]}" "efibootmgr -n 0005 | grep -E '^(BootNext|BootOrder)' && systemctl reboot" || true

sleep 15
wait_for "LibreELEC"
[ "$("${LE_SSH[@]}" cat /flash/bench-name)" = "${NAME}" ] || die "the box did not boot profile ${NAME}"
"${LE_SSH[@]}" '. /etc/os-release; echo "booted: ${PRETTY_NAME}, bench profile $(cat /flash/bench-name)"'
