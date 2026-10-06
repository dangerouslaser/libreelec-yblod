/* Test-only configuration: prove unsupported builds cannot enable the module. */
#include "/opt/ffmpeg-source/config.h"
#undef CONFIG_GPL
#undef CONFIG_VERSION3
#define CONFIG_GPL 0
#define CONFIG_VERSION3 0
