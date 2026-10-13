# SPDX-License-Identifier: GPL-2.0-or-later

PKG_NAME="skin.estuary.yblod"
PKG_VERSION="4.1.0+yblod.18"
PKG_SHA256="eee5ef76c3f6ef7377cbeecb17cc1baa89cfd3b25ac7f6a3e31b2a6020099c25"
PKG_LICENSE="GPL-2.0-only AND CC-BY-SA-4.0"
PKG_SITE="https://github.com/dangerouslaser/skin.estuary.yblod"
PKG_URL="https://github.com/dangerouslaser/skin.estuary.yblod/releases/download/v${PKG_VERSION}/${PKG_NAME}-${PKG_VERSION}.zip"
PKG_SOURCE_DIR="skin.estuary.yblod"
PKG_DEPENDS_TARGET="toolchain"
PKG_LONGDESC="Estuary YBLOD: Estuary with LG TV and Denon receiver integration (YBLOD LG edition, pre-installed Kodi add-on; formerly skin.estuary.lg)."
PKG_TOOLCHAIN="manual"

makeinstall_target() {
  mkdir -p ${INSTALL}/usr/share/kodi/addons/${PKG_NAME}
  cp -a ${PKG_BUILD}/. ${INSTALL}/usr/share/kodi/addons/${PKG_NAME}/
}
