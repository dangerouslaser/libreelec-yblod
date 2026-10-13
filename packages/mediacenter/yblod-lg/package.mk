# SPDX-License-Identifier: GPL-2.0-or-later

PKG_NAME="yblod-lg"
PKG_VERSION="1"
PKG_LICENSE="GPL-2.0-or-later"
PKG_SITE="https://github.com/dangerouslaser/libreelec-yblod"
PKG_URL=""
PKG_DEPENDS_TARGET="toolchain kodi service.webostv repository.dangerouslaser"
PKG_NEED_UNPACK="${ROOT}/yblod/editions/lg"
PKG_LONGDESC="YBLOD LG edition: LG webOS TV Control and the repository that keeps it and Estuary YBLOD updated."
PKG_TOOLCHAIN="manual"

makeinstall_target() {
  :
}

# Kodi disables add-ons it finds without having installed them. List these as optional system
# add-ons: enabled by default, and the user can still disable them. Runs at image assembly,
# after kodi has installed its manifest.
post_install() {
  local manifest=${INSTALL}/usr/share/kodi/system/addon-manifest.xml addon
  for addon in service.webostv repository.dangerouslaser; do
    grep -q ">${addon}<" ${manifest} ||
      sed -i "s|</addons>|  <addon optional=\"true\">${addon}</addon>\n</addons>|" ${manifest}
  done
}
