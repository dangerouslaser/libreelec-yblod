#define YB_EGL_BRIDGE_HOST_ONLY
#include "native_egl_output_bridge.c"
#include <assert.h>
#include <stdio.h>
struct fixture {yb_egl_binding current;unsigned waits,timed,images,textures,deletes,binds;int image_fail,texture_fail,timeout,delete_fail,restore_fail;};
static const yb_egl_binding consumer={1,2,3,4,0x30a0};
static int snap(void *u,yb_egl_binding *b){*b=((struct fixture *)u)->current;return 1;}
static int check(void *u,const yb_egl_binding *b,uintptr_t p){(void)u;return same_binding(b,&consumer)&&p==9;}
static int bind_test(void *u,const yb_egl_binding *b){struct fixture *f=u;f->binds++;if(f->restore_fail&&b->context==2)return 0;f->current=*b;return 1;}
static int wait_test(void *u){((struct fixture *)u)->waits++;return 1;}
static int timed_test(void *u,uint64_t t){struct fixture *f=u;(void)t;f->timed++;return !f->timeout;}
static int image_test(void *u,uintptr_t d,uintptr_t p,uint32_t t,uintptr_t *o){struct fixture *f=u;(void)d;(void)p;(void)t;unsigned n=++f->images;*o=100+n;return (int)n!=f->image_fail;}
static int texture_test(void *u,uintptr_t i,uint32_t *o){struct fixture *f=u;(void)i;unsigned n=++f->textures;*o=200+n;return (int)n!=f->texture_fail;}
static int del_texture(void *u,uint32_t t){struct fixture *f=u;(void)t;f->deletes++;return !f->delete_fail;}
static int del_image(void *u,uintptr_t d,uintptr_t i){struct fixture *f=u;(void)d;(void)i;f->deletes++;return !f->delete_fail;}
static yb_egl_bridge_ops ops(struct fixture *f){return (yb_egl_bridge_ops){f,snap,check,bind_test,wait_test,image_test,texture_test,del_texture,del_image};}
int main(void)
{
    unsigned cases=0;
    for(int failure=0;failure<7;failure++) {
        struct fixture f={.current=consumer};yb_egl_bridge_ops o=ops(&f);
        if(failure>0&&failure<=3)f.image_fail=failure;
        if(failure>3)f.texture_fail=failure-3;
        yb_egl_output_bridge *b[3]={0};uint32_t textures[3]={10,11,12};
        int status=yb_egl_output_bridge_create_planes_with_ops(&o,timed_test,9,textures,b);
        assert(status==(failure?YB_EGL_BRIDGE_IMPORT:YB_EGL_BRIDGE_OK));
        assert(f.waits==1&&same_binding(&f.current,&consumer));
        for(unsigned i=0;i<3;i++){assert(b[i]);assert((yb_egl_output_bridge_texture(b[i])!=0)==!failure);}
        f.timeout=1;unsigned before=f.deletes;
        assert(yb_egl_output_bridge_release_planes_timed(b,0)==YB_EGL_BRIDGE_CONSUMER);
        assert(f.deletes==before);for(unsigned i=0;i<3;i++)assert(b[i]);
        f.timeout=0;
        assert(yb_egl_output_bridge_release_planes_timed(b,100)==0);
        assert(f.timed==2&&same_binding(&f.current,&consumer));
        for(unsigned i=0;i<3;i++)assert(!b[i]);
        cases++;
    }
    {
        struct fixture f={.current=consumer};yb_egl_bridge_ops o=ops(&f);
        yb_egl_output_bridge *b[3]={0};uint32_t t[3]={10,11,12};
        assert(!yb_egl_output_bridge_create_planes_with_ops(&o,timed_test,9,t,b));
        f.delete_fail=1;assert(yb_egl_output_bridge_release_planes_timed(b,1)==YB_EGL_BRIDGE_CLEANUP);
        for(unsigned i=0;i<3;i++)assert(b[i]);
        f.delete_fail=0;
        assert(!yb_egl_output_bridge_release_planes_timed(b,1));cases++;
    }
    {
        struct fixture f={.current=consumer,.restore_fail=1};yb_egl_bridge_ops o=ops(&f);
        yb_egl_output_bridge *b[3]={0};uint32_t t[3]={10,11,12};
        assert(yb_egl_output_bridge_create_planes_with_ops(&o,timed_test,9,t,b)==YB_EGL_BRIDGE_RESTORE);
        for(unsigned i=0;i<3;i++){assert(b[i]);assert(!yb_egl_output_bridge_texture(b[i]));}
        f.restore_fail=0;assert(!yb_egl_output_bridge_release_planes_timed(b,1));cases++;
    }
    printf("{\"cases\":%u,\"pass\":true,\"gpu_tested\":false}\n",cases);
    return 0;
}
