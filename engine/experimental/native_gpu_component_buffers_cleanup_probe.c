/* Executable injected-GL cleanup tests; no context, driver or GPU work. */
#include <assert.h>
#include <stdio.h>
/* Copy this harness beside the patched backend in an isolated source tree
 * before compiling; never build it against the unpatched production file. */
#include "native_gpu_composer_backend.c"

static unsigned delete_calls, deleted_ids, fail_delete_call;
static GLenum injected_error;
static uintptr_t fake_context(void *opaque) { (void)opaque; return 1; }
static GLenum fake_error(void)
{ GLenum value=injected_error; injected_error=GL_NO_ERROR; return value; }
static void fake_delete_buffers(GLsizei count,const GLuint *ids)
{
    ++delete_calls;
    for(GLsizei i=0;i<count;i++)if(ids[i])++deleted_ids;
    if(delete_calls==fail_delete_call)injected_error=GL_INVALID_OPERATION;
}
static void fake_delete_textures(GLsizei count,const GLuint *ids)
{ (void)count;(void)ids; }
static void fake_delete_program(GLuint program) { (void)program; }
static yb_gpu_composer_backend *backend(void)
{
    yb_gpu_composer_backend *b=calloc(1,sizeof(*b));assert(b);
    b->context=1;b->owner.current_context=fake_context;
    b->gl.GetError=fake_error;b->gl.DeleteBuffers=fake_delete_buffers;
    b->gl.DeleteTextures=fake_delete_textures;b->gl.DeleteProgram=fake_delete_program;
    return b;
}
static void reset(void)
{ delete_calls=deleted_ids=fail_delete_call=0;injected_error=GL_NO_ERROR; }
int main(void)
{
    unsigned checks=0;
    /* Every possible partial GenBuffers result is zero-initialized and all
     * returned IDs reach the create-failure cleanup helper. */
    for(unsigned populated=0;populated<=4;populated++){
        reset();yb_gpu_composer_backend *b=backend();
        for(unsigned i=0;i<populated;i++)b->buffers[i]=10+i;
        delete_owned(b);assert(delete_calls==1&&deleted_ids==populated);++checks;free(b);
    }
    /* Failed deletion preserves handle and failed ID; retry cleans remaining
     * IDs without repeating successful earlier deletions. */
    for(unsigned fail_at=1;fail_at<=4;fail_at++){
        reset();yb_gpu_composer_backend *b=backend();
        for(unsigned i=0;i<4;i++)b->buffers[i]=10+i;
        fail_delete_call=fail_at;
        assert(yb_gpu_backend_destroy(&b)==YB_GPU_BACKEND_GL_FAILURE&&b);++checks;
        for(unsigned i=0;i<4;i++){assert(b->buffers[i]==(i<fail_at-1?0:10+i));}
        ++checks;
        fail_delete_call=0;
        assert(yb_gpu_backend_destroy(&b)==YB_GPU_BACKEND_OK&&!b);++checks;
    }
    reset();yb_gpu_composer_backend *b=backend();b->pending=1;b->buffers[0]=10;
    assert(yb_gpu_backend_destroy(&b)==YB_GPU_BACKEND_BUSY&&b&&delete_calls==0);++checks;
    b->pending=0;assert(yb_gpu_backend_destroy(&b)==YB_GPU_BACKEND_OK&&!b);++checks;
    printf("{\"checks\":%u,\"passed\":true,\"gpu_calls\":false,\"scope\":\"injected_cleanup_only\"}\n",checks);
    return 0;
}
