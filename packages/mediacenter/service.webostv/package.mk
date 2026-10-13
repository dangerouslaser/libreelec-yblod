# SPDX-License-Identifier: GPL-2.0-or-later

PKG_NAME="service.webostv"
PKG_VERSION="0.8.9"
PKG_SHA256="ac61f043ffd6af1e78f3a328df82cf4cb00315eea042ab5f1b1bd35cd47102ee"
PKG_LICENSE="Apache-2.0"
PKG_SITE="https://github.com/dangerouslaser/kodi-webos-control"
PKG_URL="https://github.com/dangerouslaser/kodi-webos-control/releases/download/v${PKG_VERSION}/${PKG_NAME}-${PKG_VERSION}.zip"
PKG_SOURCE_DIR="service.webostv"
PKG_DEPENDS_TARGET="toolchain"
PKG_LONGDESC="LG webOS TV Control (YBLOD LG edition, pre-installed Kodi add-on)."
PKG_TOOLCHAIN="manual"

makeinstall_target() {
  mkdir -p ${INSTALL}/usr/share/kodi/addons/${PKG_NAME}
  cp -a ${PKG_BUILD}/. ${INSTALL}/usr/share/kodi/addons/${PKG_NAME}/
}
