#include "native_egl_output_bridge.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>
typedef struct { unsigned slot,texture_deletes,image_deletes;int fail_texture; } Plane;
static yb_egl_binding binding={11,22,77,88,0x30A0};
static int snap(void *user,yb_egl_binding *out){(void)user;*out=binding;return 1;}
static int valid(void *user,const yb_egl_binding *saved,uintptr_t producer)
{(void)user;return saved->display==11&&producer==33;}
static int bind(void *user,const yb_egl_binding *value){(void)user;binding=*value;return 1;}
static int wait_default(void *user){(void)user;return 1;}
static int wait_timed(void *user,uint64_t timeout){(void)user;assert(timeout==1000);return 1;}
static int image(void *user,uintptr_t display,uintptr_t producer,uint32_t texture,uintptr_t *out)
{Plane*p=user;assert(display==11&&producer==33&&texture==44+p->slot);*out=55+p->slot;return 1;}
static int texture(void *user,uintptr_t image_id,uint32_t *out)
{Plane*p=user;assert(image_id==55+p->slot);if(p->fail_texture)return 0;*out=66+p->slot;return 1;}
static int texture_delete(void *user,uint32_t value)
{Plane*p=user;assert(value==66+p->slot);p->texture_deletes++;return 1;}
static int image_delete(void *user,uintptr_t display,uintptr_t value)
{Plane*p=user;assert(display==11&&value==55+p->slot);p->image_deletes++;return 1;}
int main(void)
{
    for(unsigned failure=0;failure<3;failure++){
        Plane states[3]={{.slot=0},{.slot=1},{.slot=2}};
        yb_egl_output_bridge *handles[3]={0};
        yb_egl_binding original=binding;
        states[failure].fail_texture=1;
        for(unsigned i=0;i<=failure;i++){
            yb_egl_bridge_ops ops={&states[i],snap,valid,bind,wait_default,image,texture,texture_delete,image_delete};
            int status=yb_egl_output_bridge_create_with_timed_ops(&ops,wait_timed,33,44+i,&handles[i]);
            assert(status==(i==failure?YB_EGL_BRIDGE_IMPORT:YB_EGL_BRIDGE_OK));
            assert(handles[i]);
            assert(yb_egl_output_bridge_texture(handles[i])==(i==failure?0:66+i));
            assert(!memcmp(&binding,&original,sizeof(binding)));
        }
        for(unsigned i=0;i<3;i++){
            assert(states[i].texture_deletes==0&&states[i].image_deletes==0);
            assert((handles[i]!=NULL)==(i<=failure));
        }
        for(unsigned i=0;i<3;i++){
            assert(yb_egl_output_bridge_release_timed(&handles[i],1000)==YB_EGL_BRIDGE_OK);
            assert(!handles[i]);
            assert(states[i].texture_deletes==(i<failure?1U:0U));
            assert(states[i].image_deletes==(i<=failure?1U:0U));
            assert(!memcmp(&binding,&original,sizeof(binding)));
        }
    }
    puts("{\"schema\":\"yblod.native-planar-bridge-ownership-host-test.v1\",\"complete\":true,\"actual_bridge_implementation\":true,\"partial_import_positions_checked\":3,\"partial_imports_retain_owned_resources\":true,\"native_context_atomic_publication_tested\":false}");
    return 0;
}
