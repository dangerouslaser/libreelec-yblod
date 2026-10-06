"""Injected lifecycle tests: no EGL context, GPU, or driver calls."""
from pathlib import Path
import hashlib
import json
import os
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent


class OutputBridgeContracts(unittest.TestCase):
    def test_bounded_lifecycle_and_failures(self):
        source = r'''
#include "native_egl_output_bridge.h"
#include <string.h>
typedef struct { yb_egl_binding current; unsigned binds,waits,td,id; int invalid,waitfail,importfail,restorefail; } State;
static int snap(void *u,yb_egl_binding *b){*b=((State*)u)->current;return 1;}
static int valid(void *u,const yb_egl_binding *b,uintptr_t p){return !((State*)u)->invalid && b->display==11 && b->context==22 && p==33;}
static int bind(void *u,const yb_egl_binding *b){State*s=u;++s->binds;if(s->restorefail && b->context==22)return 0;s->current=*b;return 1;}
static int wait(void*u){State*s=u;++s->waits;return !s->waitfail;}
static int image(void*u,uintptr_t d,uintptr_t c,uint32_t t,uintptr_t*out){(void)u;if(d!=11||c!=33||t!=44)return 0;*out=55;return 1;}
static int tex(void*u,uintptr_t i,uint32_t*out){if(i!=55)return 0;*out=66;return !((State*)u)->importfail;}
static int td(void*u,uint32_t t){if(t!=66)return 0;++((State*)u)->td;return 1;}
static int id(void*u,uintptr_t d,uintptr_t i){if(d!=11||i!=55)return 0;++((State*)u)->id;return 1;}
static State fresh(void){State s;memset(&s,0,sizeof(s));s.current=(yb_egl_binding){11,22,77,88,0x30A0};return s;}
static yb_egl_bridge_ops ops(State*s){yb_egl_bridge_ops o={s,snap,valid,bind,wait,image,tex,td,id};return o;}
#define REQUIRE(x) do{if(!(x))return __LINE__;}while(0)
int main(void){
 State s=fresh();yb_egl_binding original=s.current;yb_egl_bridge_ops o=ops(&s);yb_egl_output_bridge*b=NULL;
 REQUIRE(yb_egl_output_bridge_create_with_ops(&o,33,44,&b)==0);REQUIRE(b&&yb_egl_output_bridge_texture(b)==66);
 yb_egl_output_bridge *saved=b;REQUIRE(yb_egl_output_bridge_create_with_ops(&o,33,44,&b)==YB_EGL_BRIDGE_ARGUMENT);REQUIRE(b==saved);
 REQUIRE(!memcmp(&s.current,&original,sizeof(original)));REQUIRE(s.waits==1&&s.td==0&&s.id==0);
 s.waitfail=1;REQUIRE(yb_egl_output_bridge_release(&b)==YB_EGL_BRIDGE_CONSUMER);REQUIRE(b&&s.td==0&&s.id==0);
 REQUIRE(!memcmp(&s.current,&original,sizeof(original)));s.waitfail=0;
 REQUIRE(yb_egl_output_bridge_release(&b)==0);REQUIRE(!b&&s.td==1&&s.id==1);REQUIRE(!memcmp(&s.current,&original,sizeof(original)));
 REQUIRE(yb_egl_output_bridge_release(&b)==0);REQUIRE(s.td==1&&s.id==1);
 s=fresh();o=ops(&s);s.invalid=1;REQUIRE(yb_egl_output_bridge_create_with_ops(&o,33,44,&b)==YB_EGL_BRIDGE_UNSUPPORTED);REQUIRE(!b&&s.binds==0&&s.waits==0);
 s=fresh();o=ops(&s);s.waitfail=1;REQUIRE(yb_egl_output_bridge_create_with_ops(&o,33,44,&b)==YB_EGL_BRIDGE_PRODUCER);REQUIRE(!b&&!memcmp(&s.current,&original,sizeof(original)));
 s=fresh();o=ops(&s);s.importfail=1;REQUIRE(yb_egl_output_bridge_create_with_ops(&o,33,44,&b)==YB_EGL_BRIDGE_IMPORT);REQUIRE(b&&yb_egl_output_bridge_texture(b)==0);s.importfail=0;REQUIRE(yb_egl_output_bridge_release(&b)==0);REQUIRE(s.td==1&&s.id==1);
 s=fresh();o=ops(&s);s.restorefail=1;REQUIRE(yb_egl_output_bridge_create_with_ops(&o,33,44,&b)==YB_EGL_BRIDGE_RESTORE);REQUIRE(b&&yb_egl_output_bridge_texture(b)==0);s.restorefail=0;s.current=original;REQUIRE(yb_egl_output_bridge_release(&b)==0);
 REQUIRE(yb_egl_output_bridge_create_with_ops(NULL,33,44,&b)==YB_EGL_BRIDGE_ARGUMENT);REQUIRE(!b);
 o=ops(&s);REQUIRE(yb_egl_output_bridge_create_with_ops(&o,0,44,&b)==YB_EGL_BRIDGE_ARGUMENT);REQUIRE(!b);
 REQUIRE(yb_egl_output_bridge_release(NULL)==YB_EGL_BRIDGE_ARGUMENT);REQUIRE(yb_egl_output_bridge_texture(NULL)==0);
 REQUIRE(yb_egl_output_bridge_create(33,44,&b)==YB_EGL_BRIDGE_UNSUPPORTED);REQUIRE(!b);
 return 0;
}
'''
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            harness = path / "test.c"
            harness.write_text(source)
            binary = path / "test"
            subprocess.run([os.environ.get("CC", "cc"), "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror", "-Wconversion", "-Wshadow", "-fsanitize=undefined", "-fno-sanitize-recover=all", "-DYB_EGL_BRIDGE_HOST_ONLY", "-I", str(ROOT), str(harness), str(ROOT / "native_egl_output_bridge.c"), "-o", str(binary)], check=True, capture_output=True)
            subprocess.run([str(binary)], check=True, timeout=5, capture_output=True)

    def test_native_source_bounds_and_borrowed_display(self):
        source = (ROOT / "native_egl_output_bridge.c").read_text()
        self.assertNotIn("eglTerminate(", source)
        self.assertNotIn("glFinish(", source)
        self.assertIn("i<5 && status==GL_TIMEOUT_EXPIRED", source)
        self.assertIn("UINT64_C(1000000000)", source)
        self.assertIn("EGL_IMAGE_PRESERVED_KHR,EGL_TRUE", source)
        self.assertIn("GL_OES_EGL_image", source)

    def test_saved_synthetic_checkpoint(self):
        report = json.loads((ROOT / "EGL_OUTPUT_BRIDGE_RESULTS.json").read_text())
        self.assertEqual(report["schema"], "yblod.egl-output-bridge-checkpoint.v1")
        result = report["result"]
        self.assertEqual((result["width"], result["height"]), (4, 4))
        self.assertEqual((result["rgba32f_words_exact"], result["rgba16ui_words_exact"]), (64, 64))
        self.assertTrue(result["bindings_restored"])
        self.assertTrue(result["producer_consumer_fences"])
        self.assertFalse(result["playback_tested"])
        self.assertTrue(report["kodi_identity_unchanged"])
        self.assertTrue(report["artifacts_unchanged"])
        for name, pin in report["source_sha256"].items():
            self.assertEqual(hashlib.sha256((ROOT / Path(name).name).read_bytes()).hexdigest(), pin)
        after = report["resources_after"]
        self.assertEqual(after["memory.max"], "536870912")
        self.assertEqual((after["memory.swap.max"], after["memory.swap.current"]), ("0", "0"))
        self.assertLess(int(after["memory.peak"]), 512 * 1024 ** 2)
        events = dict(line.split() for line in after["memory.events"].splitlines())
        for name in ("high", "max", "oom", "oom_kill"):
            self.assertEqual(events[name], "0")


if __name__ == "__main__":
    unittest.main()
