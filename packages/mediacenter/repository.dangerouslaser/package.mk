# SPDX-License-Identifier: GPL-2.0-or-later

PKG_NAME="repository.dangerouslaser"
PKG_VERSION="1.0.1"
PKG_SHA256="72d216ed702fff12e9bdc1e702f78b65bc74a6cb8c7ff9d31f58d834e07b82e6"
PKG_LICENSE="GPL-2.0-or-later"
PKG_SITE="https://github.com/dangerouslaser/dangerouslaser.github.io"
PKG_URL="https://dangerouslaser.github.io/${PKG_NAME}/${PKG_NAME}-${PKG_VERSION}.zip"
PKG_SOURCE_DIR="repository.dangerouslaser"
PKG_DEPENDS_TARGET="toolchain"
PKG_LONGDESC="dangerouslaser Kodi add-on repository, for updates of the LG add-ons (YBLOD LG edition, pre-installed Kodi add-on)."
PKG_TOOLCHAIN="manual"

makeinstall_target() {
  mkdir -p ${INSTALL}/usr/share/kodi/addons/${PKG_NAME}
  cp -a ${PKG_BUILD}/. ${INSTALL}/usr/share/kodi/addons/${PKG_NAME}/
}
