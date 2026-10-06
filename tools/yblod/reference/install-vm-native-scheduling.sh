#!/bin/sh
# Install a scheduling candidate only from the qualified, inactive baseline.
set -eu
test "$#" = 1
candidate=/storage/yblod-renderer-step1-20261006/kodi-native-scheduling.bin
baseline=/storage/yblod-renderer-step1-20261006/kodi-native-planar-gles.bin
baseline_hash=2f636c24c0ade31d838aa849ab98123d3f9cb308d69bee87851aad0d3f6b18c1
test "$(systemctl show kodi -p ActiveState --value)" = inactive
test "$(systemctl show kodi -p MainPID --value)" = 0
test "$(sha256sum "$baseline" | awk '{print $1}')" = "$baseline_hash"
test "$(sha256sum /usr/lib/kodi/kodi.bin | awk '{print $1}')" = "$baseline_hash"
test "$(sha256sum "$candidate" | awk '{print $1}')" = "$1"
chmod 755 "$candidate"
umount /usr/lib/kodi/kodi.bin
if ! mount --bind "$candidate" /usr/lib/kodi/kodi.bin; then
  mount --bind "$baseline" /usr/lib/kodi/kodi.bin
  exit 1
fi
if test "$(sha256sum /usr/lib/kodi/kodi.bin | awk '{print $1}')" != "$1"; then
  umount /usr/lib/kodi/kodi.bin
  mount --bind "$baseline" /usr/lib/kodi/kodi.bin
  exit 1
fi
echo 'Verified scheduling candidate installed; Kodi remains inactive.'
