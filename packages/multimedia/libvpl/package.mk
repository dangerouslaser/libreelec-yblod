# SPDX-License-Identifier: GPL-2.0-or-later

PKG_NAME="libvpl"
PKG_VERSION="2.17.0"
PKG_SHA256="4de3e2faf1e8307fb282e4a43f443191810f6a6b0a484fffa7995ba1c814c6ec"
PKG_ARCH="x86_64"
PKG_LICENSE="MIT"
PKG_SITE="https://github.com/intel/libvpl"
PKG_URL="https://github.com/intel/libvpl/archive/refs/tags/v${PKG_VERSION}.tar.gz"
PKG_DEPENDS_TARGET="toolchain"
PKG_LONGDESC="Intel VPL dispatcher and development headers for the opt-in QSV decode experiment."
PKG_BUILD_FLAGS="+bfd -lto -lto-fat +lto-off"

# Dispatcher only: never install host libraries, examples or extra tools.
PKG_CMAKE_OPTS_TARGET="-DBUILD_SHARED_LIBS=ON \
                       -DBUILD_TESTS=OFF \
                       -DBUILD_EXAMPLES=OFF \
                       -DINSTALL_EXAMPLES=OFF \
                       -DINSTALL_DEV=ON \
                       -DINSTALL_LIB=ON \
                       -DENABLE_LIBDIR_IN_RUNTIME_SEARCH=ON \
                       -DCMAKE_INTERPROCEDURAL_OPTIMIZATION=OFF"
