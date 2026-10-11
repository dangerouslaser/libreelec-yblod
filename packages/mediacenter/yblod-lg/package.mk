# SPDX-License-Identifier: GPL-2.0-or-later

PKG_NAME="yblod-lg"
PKG_VERSION="1"
PKG_LICENSE="GPL-2.0-or-later"
PKG_SITE="https://github.com/dangerouslaser/libreelec-yblod"
PKG_URL=""
PKG_DEPENDS_TARGET="toolchain skin.estuary.lg service.webostv repository.dangerouslaser"
PKG_LONGDESC="YBLOD LG edition: Estuary LG, LG webOS TV Control and their repository, with Estuary LG as the skin of a fresh installation."
PKG_TOOLCHAIN="manual"

makeinstall_target() {
  mkdir -p ${INSTALL}/usr/lib/yblod-lg ${INSTALL}/usr/lib/systemd/system/kodi.service.d
  cp ${PKG_DIR}/files/first-run-defaults ${INSTALL}/usr/lib/yblod-lg/
  chmod 0755 ${INSTALL}/usr/lib/yblod-lg/first-run-defaults
  cp ${PKG_DIR}/files/30-yblod-lg.conf ${INSTALL}/usr/lib/systemd/system/kodi.service.d/
}
