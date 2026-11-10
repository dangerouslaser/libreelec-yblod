# SPDX-License-Identifier: MIT

PKG_NAME="yblod-engine-vk"
PKG_VERSION="0.1.0"
PKG_ARCH="x86_64"
PKG_LICENSE="GPL-3.0-or-later AND MIT AND LGPL-2.1-or-later"
PKG_SITE="https://github.com/dangerouslaser/libreelec-yblod"
PKG_URL=""
PKG_DEPENDS_TARGET="toolchain cargo:host shaderc:host ffmpeg libva mesa vulkan-loader vulkan-headers"
# The crate is yblod-engine/vk; it compiles yblod's host C from yblod-engine/src.
# YBLOD's only Dolby Vision engine (0.4.0): it also installs Kodi's runtime
# environment, the service drop-in, dv-diagnostics and dv-prepare (the boot
# service that builds the engine's pipeline cache after an update).
PKG_NEED_UNPACK="${ROOT}/yblod-engine/vk ${ROOT}/yblod-engine/src ${ROOT}/yblod-engine/integration ${ROOT}/yblod-engine/tools/dv-diagnostics"
PKG_LONGDESC="yblod's Dolby Vision source-tunnel engine on Vulkan compute (libdv_engine_vk.so.1, big-fella's dv-engine-vk)"
PKG_TOOLCHAIN="manual"
PKG_BUILD_FLAGS="-lto"

unpack() {
  mkdir -p "${PKG_BUILD}"
  cp -a "${ROOT}/yblod-engine/vk/." "${PKG_BUILD}/"
  rm -rf "${PKG_BUILD}/target"
}

make_target() {
  export RUSTC_LINKER=${CC}
  export GLSLC="${TOOLCHAIN}/bin/glslc"
  export YBLOD_ENGINE_SRC="${ROOT}/yblod-engine/src"
  export FFMPEG_INCLUDE="${SYSROOT_PREFIX}/usr/include"
  # The library; the other test tools need EGL and the OpenCL engine.
  cargo build \
    --target ${TARGET_NAME} \
    --release \
    --locked \
    --lib

  # dvvk-prepare (big-fella's tool): opens the installed engine with every pack
  # variant built, no media or display, so its pipeline cache is ready.
  ${CC} ${CFLAGS} -Wall -Wextra -I"${PKG_BUILD}/include" \
    "${PKG_BUILD}/tools/dvvk-prepare.c" -o "${PKG_BUILD}/dvvk-prepare" \
    ${LDFLAGS} $(pkg-config --libs gbm libva libva-drm) -ldl
}

makeinstall_target() {
  local lib="${PKG_BUILD}/.${TARGET_NAME}/target/${TARGET_NAME}/release/libdv_engine_vk.so"
  # The soname: DVVK_LIBRARY in the header, its one place (build.rs links it in).
  local soname
  soname=$(sed -n 's/^#define DVVK_LIBRARY "\(.*\)"/\1/p' "${PKG_BUILD}/include/dv_engine_vk.h")
  [ -n "${soname}" ] || die "no DVVK_LIBRARY in dv_engine_vk.h"

  mkdir -p "${INSTALL}/usr/lib"
  cp "${lib}" "${INSTALL}/usr/lib/${soname}"

  # Kodi's adapter includes the C API; the library itself is dlopened.
  mkdir -p "${SYSROOT_PREFIX}/usr/include/dv-engine-vk"
  cp "${PKG_BUILD}/include/dv_engine_vk.h" "${PKG_BUILD}/include/dvvk_plan.h" \
     "${SYSROOT_PREFIX}/usr/include/dv-engine-vk/"

  # Kodi's Dolby Vision environment (installed names stay native-dv).
  mkdir -p "${INSTALL}/usr/lib/kodi" "${INSTALL}/usr/lib/systemd/system/kodi.service.d" "${INSTALL}/usr/bin"
  cp "${ROOT}/yblod-engine/integration/runtime.env" "${INSTALL}/usr/lib/kodi/native-dv.env"
  cp "${ROOT}/yblod-engine/integration/20-native-dv.conf" \
     "${INSTALL}/usr/lib/systemd/system/kodi.service.d/"
  cp "${ROOT}/yblod-engine/tools/dv-diagnostics" "${INSTALL}/usr/bin/dv-diagnostics"
  chmod 0755 "${INSTALL}/usr/bin/dv-diagnostics"

  # The pipeline cache after an update (yblod-dv-prepare.service).
  mkdir -p "${INSTALL}/usr/lib/yblod"
  cp "${PKG_BUILD}/dvvk-prepare" "${ROOT}/yblod-engine/integration/dv-prepare" \
     "${INSTALL}/usr/lib/yblod/"
  chmod 0755 "${INSTALL}/usr/lib/yblod/dvvk-prepare" "${INSTALL}/usr/lib/yblod/dv-prepare"
  cp "${ROOT}/yblod-engine/integration/yblod-dv-prepare.service" \
     "${INSTALL}/usr/lib/systemd/system/"

  # Licences: yblod's host C (yblod-engine/src) and the engine's own.
  mkdir -p "${INSTALL}/usr/share/licenses/native-dv" "${INSTALL}/usr/share/licenses/dv-engine-vk"
  cp "${ROOT}/yblod-engine/LICENSE" "${ROOT}/yblod-engine/SOURCES.md" \
     "${INSTALL}/usr/share/licenses/native-dv/"
  cp -r "${ROOT}/yblod-engine/LICENSES/." "${INSTALL}/usr/share/licenses/native-dv/"
  cp -r "${PKG_BUILD}/LICENSES/." "${INSTALL}/usr/share/licenses/dv-engine-vk/"
}

post_install() {
  enable_service yblod-dv-prepare.service
}
