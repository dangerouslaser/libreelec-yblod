# SPDX-License-Identifier: GPL-2.0-or-later

PKG_NAME="repository.dangerouslaser"
PKG_VERSION="1.0.1"
PKG_LICENSE="GPL-2.0-or-later"
PKG_SITE="https://github.com/dangerouslaser/dangerouslaser.github.io"
PKG_URL=""
PKG_DEPENDS_TARGET="toolchain"
PKG_LONGDESC="dangerouslaser Kodi add-on repository, for updates of the LG add-ons (YBLOD LG edition, pre-installed Kodi add-on)."
PKG_TOOLCHAIN="manual"

makeinstall_target() {
  mkdir -p ${INSTALL}/usr/share/kodi/addons/${PKG_NAME}
  # The published zip is regenerated with new timestamps on every repository publish, so its
  # checksum is not stable; the add-on is a single addon.xml, kept here.
  cp ${PKG_DIR}/files/addon.xml ${INSTALL}/usr/share/kodi/addons/${PKG_NAME}/
}
