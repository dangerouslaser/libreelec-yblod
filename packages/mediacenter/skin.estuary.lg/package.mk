# SPDX-License-Identifier: GPL-2.0-or-later

PKG_NAME="skin.estuary.lg"
PKG_VERSION="4.1.0+lg.7"
PKG_SHA256="67945e0785e327977e8ed4fa51afbbe341bb71d64a1f357b1cee3c6e0eebc10f"
PKG_LICENSE="GPL-2.0-only AND CC-BY-SA-4.0"
PKG_SITE="https://github.com/dangerouslaser/skin.estuary.lg"
PKG_URL="https://github.com/dangerouslaser/skin.estuary.lg/releases/download/v${PKG_VERSION}/${PKG_NAME}-${PKG_VERSION}.zip"
PKG_SOURCE_DIR="skin.estuary.lg"
PKG_DEPENDS_TARGET="toolchain"
PKG_LONGDESC="Estuary with LG TV integration (YBLOD LG edition, pre-installed Kodi add-on)."
PKG_TOOLCHAIN="manual"

makeinstall_target() {
  mkdir -p ${INSTALL}/usr/share/kodi/addons/${PKG_NAME}
  cp -a ${PKG_BUILD}/. ${INSTALL}/usr/share/kodi/addons/${PKG_NAME}/
}
