# SPDX-License-Identifier: GPL-2.0-or-later

PKG_NAME="skin.estuary.yblod"
PKG_VERSION="4.1.0+yblod.22"
PKG_SHA256="bbf2689ffd00a0cd570bad8bb4b6b30557f1f7ac2c24646a0b2c018b0ab5728d"
PKG_LICENSE="GPL-2.0-only AND CC-BY-SA-4.0"
PKG_SITE="https://github.com/dangerouslaser/skin.estuary.yblod"
PKG_URL="https://github.com/dangerouslaser/skin.estuary.yblod/releases/download/v${PKG_VERSION}/${PKG_NAME}-${PKG_VERSION}.zip"
PKG_SOURCE_DIR="skin.estuary.yblod"
PKG_DEPENDS_TARGET="toolchain kodi"
PKG_NEED_UNPACK="${ROOT}/yblod/skin"
PKG_LONGDESC="Estuary YBLOD: Estuary with the Dolby Vision process info panel and LG TV integration (YBLOD default skin, pre-installed Kodi add-on)."
PKG_TOOLCHAIN="manual"

makeinstall_target() {
  mkdir -p ${INSTALL}/usr/share/kodi/addons/${PKG_NAME}
  cp -a ${PKG_BUILD}/. ${INSTALL}/usr/share/kodi/addons/${PKG_NAME}/

  # The skin was skin.estuary.lg (Estuary LG) up to 4.1.0+lg.16; move boxes still set to it.
  mkdir -p ${INSTALL}/usr/lib/yblod ${INSTALL}/usr/lib/systemd/system/kodi.service.d
  cp ${ROOT}/yblod/skin/skin-move ${INSTALL}/usr/lib/yblod/
  chmod 0755 ${INSTALL}/usr/lib/yblod/skin-move
  cp ${ROOT}/yblod/skin/30-yblod-skin.conf ${INSTALL}/usr/lib/systemd/system/kodi.service.d/
}

# Kodi disables add-ons it finds without having installed them. List the skin as an optional
# system add-on: enabled by default, and updated from a repository that carries a newer version
# (Kodi patch 20). Make it Kodi's default skin: it applies to fresh installations and to boxes on
# the default skin, never to a skin the user chose. Runs at image assembly, after kodi has
# installed its manifest and appliance settings.
post_install() {
  local manifest=${INSTALL}/usr/share/kodi/system/addon-manifest.xml
  local appliance=${INSTALL}/usr/share/kodi/system/settings/appliance.xml
  grep -q ">${PKG_NAME}<" ${manifest} ||
    sed -i "s|</addons>|  <addon optional=\"true\">${PKG_NAME}</addon>\n</addons>|" ${manifest}
  if ! grep -q ">${PKG_NAME}<" ${appliance}; then
    grep -q 'section id="interface"' ${appliance} && die "appliance.xml already has an interface section"
    sed -i "s|</settings>|  <section id=\"interface\">\n    <category id=\"skin\">\n      <group id=\"1\">\n        <setting id=\"lookandfeel.skin\">\n          <default>${PKG_NAME}</default>\n        </setting>\n      </group>\n    </category>\n  </section>\n</settings>|" ${appliance}
  fi
}
