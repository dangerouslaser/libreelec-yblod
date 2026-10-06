#ifndef YB_LIBPLACEBO_RESHAPE_H
#define YB_LIBPLACEBO_RESHAPE_H
#include <stddef.h>
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif
/* No file I/O or GPU objects. Caller frees returned bounded GLSL fragment. */
int yb_libplacebo_reshape_fragment(const int64_t metadata[3][419],char **text,size_t *bytes);
#ifdef __cplusplus
}
#endif
#endif
