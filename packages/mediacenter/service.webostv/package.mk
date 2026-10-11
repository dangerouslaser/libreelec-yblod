# SPDX-License-Identifier: GPL-2.0-or-later

PKG_NAME="service.webostv"
PKG_VERSION="0.5.3"
PKG_SHA256="99f742e9e7f1accc834329bb9e2449d19c012500dd7c18e1f2ab6de0967db0a9"
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
