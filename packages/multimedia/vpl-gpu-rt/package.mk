# SPDX-License-Identifier: GPL-2.0-or-later

PKG_NAME="vpl-gpu-rt"
PKG_VERSION="26.3.5"
PKG_SHA256="92867a0f8c09d81419102a61713e9f98dfd2af3fc9c91c6f4fb6d0c784c8e442"
PKG_ARCH="x86_64"
PKG_LICENSE="MIT"
PKG_SITE="https://github.com/intel/vpl-gpu-rt"
PKG_URL="https://github.com/intel/vpl-gpu-rt/archive/refs/tags/intel-onevpl-${PKG_VERSION}.tar.gz"
PKG_DEPENDS_TARGET="toolchain libva libdrm"
PKG_LONGDESC="Intel VPL GPU implementation for the opt-in QSV decode experiment; uses the existing VAAPI driver."
PKG_BUILD_FLAGS="+bfd -lto -lto-fat +lto-off"

pre_configure_target() {
  # Upstream accepts an environment header override; never use host SDK headers.
  unset MFX_HOME
}

# Keep upstream runtime/codec capabilities. Use shipped kernels, not a new
# GPU compiler stack; this experiment does not change the media-driver package.
PKG_CMAKE_OPTS_TARGET="-DBUILD_RUNTIME=ON \
                       -DBUILD_TESTS=OFF \
                       -DBUILD_MOCK_TESTS=OFF \
                       -DBUILD_TOOLS=OFF \
                       -DBUILD_TUTORIALS=OFF \
                       -DBUILD_KERNELS=OFF \
                       -DENABLE_OPENCL=OFF \
                       -DENABLE_ITT=OFF \
                       -DMFX_ENABLE_PXP=OFF \
                       -DCMAKE_INTERPROCEDURAL_OPTIMIZATION=OFF"
