/* Open the actual installed engine eagerly. No media, output surface or audio.
 * Keep node selection identical to mpv's open_gbm. The supervisor owns deadlines.
 */
#include "../include/dv_engine_vk.h"
#include <gbm.h>
#include <va/va.h>
#include <va/va_drm.h>
#include <fcntl.h>
#include <dlfcn.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>
int main(void) {
    signal(SIGPIPE, SIG_IGN); /* A closed progress reader is not an engine fault. */
    setvbuf(stdout, NULL, _IOLBF, 0);
    setenv("DVVK_PREPARE_PROGRESS", "1", 1);
    /* The HDR10 and HDR10+ pack variants too (a player's engine makes them on
     * first use: without them here, that is a compile in its render thread).
     * DVVK_PREPARE_MAP=0 in the environment leaves them out. */
    setenv("DVVK_PREPARE_MAP", "1", 0);
    setenv("DVVK_LAZY_RESIZED_PACK", "0", 1);
    setenv("DVVK_GPU_BOOST", "0", 1);
    const char *node = getenv("MPV_DV_RENDER_NODE");
    int fd = -1;
    struct gbm_device *gbm = NULL;
    for (int n = 128; n < 136 && !gbm; n++) {
        char path[256];
        if (node && *node) { snprintf(path, sizeof(path), "%s", node); n = 136; }
        else snprintf(path, sizeof(path), "/dev/dri/renderD%d", n);
        fd = open(path, O_RDWR | O_CLOEXEC);
        if (fd < 0) continue;
        gbm = gbm_create_device(fd);
        if (!gbm) { close(fd); fd = -1; }
    }
    if (!gbm) return 1;
    VADisplay va = vaGetDisplayDRM(fd);
    int major, minor;
    if (!va || vaInitialize(va, &major, &minor)) return 1;
    const char *library = getenv("DV_VULKAN_ENGINE_LIBRARY");
    if (!library || !*library) library = DVVK_LIBRARY;
    void *lib = dlopen(library, RTLD_NOW | RTLD_LOCAL);
    if (!lib) { fprintf(stderr, "%s\n", dlerror()); return 1; }
    int (*create)(int, void *, dvvk_engine **) = dlsym(lib, "dvvk_create");
    void (*destroy)(dvvk_engine *) = dlsym(lib, "dvvk_destroy");
    if (!create || !destroy) return 1;
    dvvk_engine *engine = NULL;
    int result = create(fd, va, &engine);
    if (result || !engine) return 1;
    destroy(engine);
    dlclose(lib);
    vaTerminate(va);
    gbm_device_destroy(gbm);
    close(fd);
    puts("DVVK_PREPARE_READY");
    return 0;
}
