# SPDX-License-Identifier: GPL-2.0-or-later

PKG_NAME="yblod-iphone-remote"
PKG_VERSION="0.1.0"
PKG_ARCH="x86_64"
PKG_LICENSE="Apache-2.0"
PKG_SITE="https://github.com/dangerouslaser/libreelec-yblod"
PKG_URL=""
PKG_DEPENDS_TARGET="toolchain cargo:host kodi"
# big-fella-remote and bf-daemon are big-fella's crates, vendored as they are
# (yblod/iphone-remote/README.md); libreelec/ is this image's side.
PKG_NEED_UNPACK="${ROOT}/yblod/iphone-remote"
PKG_LONGDESC="The box in the iPhone's Control Center remote (big-fella-remote), with Kodi as its home screen"
PKG_TOOLCHAIN="manual"

unpack() {
  mkdir -p "${PKG_BUILD}"
  cp -a "${ROOT}/yblod/iphone-remote/." "${PKG_BUILD}/"
  rm -rf "${PKG_BUILD}/big-fella-remote/target" "${PKG_BUILD}/bf-daemon/target"
}

make_target() {
  cd "${PKG_BUILD}/big-fella-remote"
  export RUSTC_LINKER=${CC}
  cargo build \
    --target ${TARGET_NAME} \
    --release \
    --locked \
    --bins
}

makeinstall_target() {
  local bin="${CARGO_TARGET_DIR}/${TARGET_NAME}/release"
  local le="${PKG_BUILD}/libreelec"
  mkdir -p ${INSTALL}/usr/bin ${INSTALL}/usr/lib/iphone-remote ${INSTALL}/usr/share/iphone-remote \
    ${INSTALL}/usr/lib/systemd/system ${INSTALL}/usr/share/kodi/addons
  cp ${bin}/big-fella-remote ${bin}/big-fella-remote-kodi ${INSTALL}/usr/bin/
  cp ${le}/iphone-remote-start ${INSTALL}/usr/lib/iphone-remote/
  chmod 0755 ${INSTALL}/usr/lib/iphone-remote/iphone-remote-start
  cp ${le}/remote.toml.in ${INSTALL}/usr/share/iphone-remote/
  cp ${le}/iphone-remote.service ${le}/iphone-remote-kodi.service ${INSTALL}/usr/lib/systemd/system/
  cp -a ${le}/script.yblod.iphoneremote ${INSTALL}/usr/share/kodi/addons/
  cp ${PKG_BUILD}/big-fella-remote/README.md ${INSTALL}/usr/share/iphone-remote/
}

# Kodi disables add-ons it finds without having installed them: the settings
# add-on is an optional system add-on (enabled by default).
post_install() {
  local manifest=${INSTALL}/usr/share/kodi/system/addon-manifest.xml
  grep -q ">script.yblod.iphoneremote<" ${manifest} ||
    sed -i "s|</addons>|  <addon optional=\"true\">script.yblod.iphoneremote</addon>\n</addons>|" ${manifest}
  enable_service iphone-remote.service
  enable_service iphone-remote-kodi.service
}
