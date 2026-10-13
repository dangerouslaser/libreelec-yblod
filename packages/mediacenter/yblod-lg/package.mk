# SPDX-License-Identifier: GPL-2.0-or-later

PKG_NAME="yblod-lg"
PKG_VERSION="1"
PKG_LICENSE="GPL-2.0-or-later"
PKG_SITE="https://github.com/dangerouslaser/libreelec-yblod"
PKG_URL=""
PKG_DEPENDS_TARGET="toolchain kodi skin.estuary.yblod service.webostv repository.dangerouslaser"
PKG_NEED_UNPACK="${ROOT}/yblod/editions/lg"
PKG_LONGDESC="YBLOD LG edition: Estuary YBLOD, LG webOS TV Control and their repository, with Estuary YBLOD as the skin of a fresh installation."
PKG_TOOLCHAIN="manual"

makeinstall_target() {
  mkdir -p ${INSTALL}/usr/lib/yblod-lg ${INSTALL}/usr/lib/systemd/system/kodi.service.d
  cp ${ROOT}/yblod/editions/lg/first-run-defaults ${INSTALL}/usr/lib/yblod-lg/
  chmod 0755 ${INSTALL}/usr/lib/yblod-lg/first-run-defaults
  cp ${ROOT}/yblod/editions/lg/30-yblod-lg.conf ${INSTALL}/usr/lib/systemd/system/kodi.service.d/
}

# Kodi disables add-ons it finds without having installed them. List these as optional system
# add-ons: enabled by default, and the user can still disable them. Runs at image assembly,
# after kodi has installed its manifest.
post_install() {
  local manifest=${INSTALL}/usr/share/kodi/system/addon-manifest.xml addon
  for addon in skin.estuary.yblod service.webostv repository.dangerouslaser; do
    grep -q ">${addon}<" ${manifest} ||
      sed -i "s|</addons>|  <addon optional=\"true\">${addon}</addon>\n</addons>|" ${manifest}
  done
}
