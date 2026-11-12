#!/bin/bash
# SPDX-License-Identifier: GPL-2.0-only
#
# install-image.sh BOX NAME KERNEL SYSTEM [PUBKEY]
#
# Installs a LibreELEC image as bench profile NAME on the N150 and boots it.
# Runs on the workstation. BOX is root@address; KERNEL and SYSTEM are the
# image's two files (target/*.kernel and *.system, or from the release .tar);
# PUBKEY (default ~/.ssh/id_ed25519.pub) is put into the profile's
# authorized_keys.
#
# The N150 dual-boots: big-fella (first in BootOrder) and LibreELEC (UEFI
# entry "UEFI OS", booted once with efibootmgr -n). LibreELEC's System
# partition also holds big-fella's boot loader, so the only thing written
# there is what /var/lib/yblod-bench/le-switch.sh on the box writes: KERNEL,
# SYSTEM, syslinux.cfg, EFI/BOOT/grub.cfg, mount-storage.sh and bench-name.
# The profile's /storage is Storage:/.bench/NAME: new for a new NAME, kept
# for one that exists. Nothing else on the box is changed, BootOrder
# included. The script stops if anything is playing in either system.

set -euo pipefail

[ $# -ge 4 ] || { sed -n '3,9p' "$0"; exit 2; }
BOX="$1"
NAME="$2"
KERNEL="$3"
SYSTEM="$4"
PUBKEY="${5:-${HOME}/.ssh/id_ed25519.pub}"

BENCH=/var/lib/yblod-bench
BACKUP=/var/lib/yblod-le-backup
LE_ENTRY="UEFI OS"
# LibreELEC has a new host key in every profile; big-fella is a known host.
LE_SSH=(ssh -o BatchMode=yes -o ConnectTimeout=8 -o UserKnownHostsFile=/dev/null
        -o StrictHostKeyChecking=no -o LogLevel=ERROR "${BOX}")
BF_SSH=(ssh -o BatchMode=yes -o ConnectTimeout=8 "${BOX}")

die() {
  echo "install-image: $*" >&2
  exit 1
}

[[ "${NAME}" =~ ^[a-z0-9][a-z0-9._-]*$ ]] || die "NAME: lower-case letters, digits, . _ -"
[ -f "${KERNEL}" ] && [ -f "${SYSTEM}" ] || die "KERNEL or SYSTEM is not a file"
[ -f "${PUBKEY}" ] || die "no public key ${PUBKEY}"

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
  echo "LibreELEC is running: checking that nothing plays, then rebooting to big-fella"
  players=$("${LE_SSH[@]}" "curl -s -m 5 -u kodi:bench -H 'Content-Type: application/json' \
    -d '{\"jsonrpc\":\"2.0\",\"method\":\"Player.GetActivePlayers\",\"id\":1}' \
    http://127.0.0.1:8080/jsonrpc || printf '%s' \
    '{\"jsonrpc\":\"2.0\",\"method\":\"Player.GetActivePlayers\",\"id\":1}' | nc -w 3 127.0.0.1 9090")
  [ "${players}" = '{"id":1,"jsonrpc":"2.0","result":[]}' ] ||
    die "Kodi is playing or does not answer (${players}): not rebooting"
  "${LE_SSH[@]}" reboot || true
  sleep 15
  wait_for "Arch Linux"
fi
[ "$(running)" = "Arch Linux" ] || die "the box runs neither big-fella nor LibreELEC"

# big-fella plays with mpv through the HDMI audio device.
IDLE='! pgrep -x mpv >/dev/null && ! grep -qs RUNNING /proc/asound/card*/pcm*p/sub*/status'
"${BF_SSH[@]}" "${IDLE}" || die "big-fella is playing something: not touching the box"

"${BF_SSH[@]}" "test -x ${BENCH}/le-switch.sh && test -f ${BACKUP}/KERNEL &&
  efibootmgr | grep -q '^BootOrder: 0000,' &&
  efibootmgr | grep -q '^Boot0005\* ${LE_ENTRY}'" ||
  die "the box is not set up as this script expects (le-switch.sh, backup, boot entries)"

need=$(($(stat -L -c %s "${KERNEL}" 2>/dev/null || stat -L -f %z "${KERNEL}") +
        $(stat -L -c %s "${SYSTEM}" 2>/dev/null || stat -L -f %z "${SYSTEM}")))
"${BF_SSH[@]}" "set -e
  free=\$(df --output=avail -B1 /var/lib | tail -n 1)
  [ \"\${free}\" -gt $((need + 1073741824)) ] || { echo 'big-fella: not enough space' >&2; exit 1; }
  mkdir -p /mnt/lesys
  mountpoint -q /mnt/lesys || mount -o ro /dev/mmcblk0p1 /mnt/lesys
  size=\$(df --output=size -B1 /mnt/lesys | tail -n 1)
  used=\$(df --output=used -B1 /mnt/lesys | tail -n 1)
  old=\$((\$(stat -c %s /mnt/lesys/KERNEL) + \$(stat -c %s /mnt/lesys/SYSTEM)))
  umount /mnt/lesys
  [ \$((used - old + ${need} + 8388608)) -lt \"\${size}\" ] ||
    { echo 'System partition: the image does not fit' >&2; exit 1; }
  mkdir -p ${BENCH}/${NAME}" || die "space check failed"

echo "copying KERNEL and SYSTEM to ${BOX}:${BENCH}/${NAME}"
scp -q "${KERNEL}" "${BOX}:${BENCH}/${NAME}/KERNEL"
scp -q "${SYSTEM}" "${BOX}:${BENCH}/${NAME}/SYSTEM"
sum() {
  (sha256sum "$1" 2>/dev/null || shasum -a 256 "$1") | cut -d' ' -f1
}
remote=$("${BF_SSH[@]}" "sha256sum ${BENCH}/${NAME}/KERNEL ${BENCH}/${NAME}/SYSTEM | cut -d' ' -f1")
[ "${remote}" = "$(sum "${KERNEL}")"$'\n'"$(sum "${SYSTEM}")" ] || die "checksums differ after the copy"

key=$(cut -d' ' -f1,2 "${PUBKEY}")
"${BF_SSH[@]}" "set -e
  mkdir -p /mnt/lestor
  mountpoint -q /mnt/lestor || mount /dev/mmcblk0p2 /mnt/lestor
  mkdir -p /mnt/lestor/.bench/${NAME}/.ssh
  chmod 700 /mnt/lestor/.bench/${NAME}/.ssh
  grep -qsF '${key}' /mnt/lestor/.bench/${NAME}/.ssh/authorized_keys ||
    echo '${key}' >> /mnt/lestor/.bench/${NAME}/.ssh/authorized_keys
  chmod 600 /mnt/lestor/.bench/${NAME}/.ssh/authorized_keys
  sync
  umount /mnt/lestor
  ${BENCH}/le-switch.sh ${NAME}" || die "the profile or the System partition was not written"

"${BF_SSH[@]}" "${IDLE}" || die "big-fella started playing: not rebooting (the image is installed)"
"${BF_SSH[@]}" "efibootmgr -n 0005 | grep -E '^(BootNext|BootOrder)' && systemctl reboot" || true

sleep 15
wait_for "LibreELEC"
"${LE_SSH[@]}" '. /etc/os-release; echo "booted: ${PRETTY_NAME}, bench profile $(cat /flash/bench-name)"'
[ "$("${LE_SSH[@]}" cat /flash/bench-name)" = "${NAME}" ] || die "the box did not boot profile ${NAME}"
