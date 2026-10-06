"""Timed consumer-release control-flow checks, no GPU or EGL runtime."""
from pathlib import Path
import hashlib
import json
import os
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent


class TimedRelease(unittest.TestCase):
    def test_actual_timed_release_checkpoint(self):
        report = json.loads((ROOT / "EGL_OUTPUT_BRIDGE_TIMED_RESULTS.json").read_text())
        self.assertEqual(report["schema"], "yblod.egl-output-bridge-timed-checkpoint.v1")
        result = report["result"]
        self.assertEqual((result["rgba32f_words_exact"], result["rgba16ui_words_exact"]), (64, 64))
        for name in ("timed_consumer_release", "bindings_restored", "producer_consumer_fences"):
            self.assertTrue(result[name])
        self.assertFalse(result["playback_tested"])
        for name, expected in report["source_sha256"].items():
            self.assertEqual(hashlib.sha256((ROOT / Path(name).name).read_bytes()).hexdigest(), expected)
        for name in ("kodi_active_before_after", "kodi_identity_unchanged", "artifacts_unchanged"):
            self.assertTrue(report[name])
        resources = report["resources_after"]
        self.assertEqual(resources["memory.max"], "536870912")
        self.assertEqual((resources["memory.swap.max"], resources["memory.swap.current"]), ("0", "0"))
        self.assertLess(int(resources["memory.peak"]), 536870912)
        self.assertTrue(all(value == "0" for name, value in
                            (line.split() for line in resources["memory.events"].splitlines())))

    def test_atomic_timeout_poll_retry(self):
        source = r'''
#include "native_egl_output_bridge.h"
#include <string.h>
typedef struct { yb_egl_binding binding; unsigned waits,deletes; uint64_t timeout; int done; } State;
static int snapshot(void *u,yb_egl_binding *b){*b=((State*)u)->binding;return 1;}
static int validate(void *u,const yb_egl_binding *b,uintptr_t p){(void)u;return b->display==11 && p==33;}
static int bind(void *u,const yb_egl_binding *b){((State*)u)->binding=*b;return 1;}
static int wait_default(void *u){(void)u;return 1;}
static int wait_timed(void *u,uint64_t timeout){State*s=u;s->timeout=timeout;s->waits++;return s->done;}
static int image(void *u,uintptr_t d,uintptr_t c,uint32_t t,uintptr_t *o){(void)u;(void)d;(void)c;(void)t;*o=55;return 1;}
static int texture(void *u,uintptr_t i,uint32_t *o){(void)u;(void)i;*o=66;return 1;}
static int delete_texture(void *u,uint32_t t){(void)t;((State*)u)->deletes++;return 1;}
static int delete_image(void *u,uintptr_t d,uintptr_t i){(void)d;(void)i;((State*)u)->deletes++;return 1;}
#define CHECK(x) do{if(!(x))return __LINE__;}while(0)
int main(void){
 State s={{11,22,77,88,0x30A0},0,0,0,0};yb_egl_binding saved=s.binding;
 yb_egl_bridge_ops o={&s,snapshot,validate,bind,wait_default,image,texture,delete_texture,delete_image};
 yb_egl_output_bridge *b=NULL;
 CHECK(yb_egl_output_bridge_create_with_timed_ops(&o,wait_timed,33,44,&b)==0);
 yb_egl_output_bridge *owned=b;
 CHECK(yb_egl_output_bridge_create_with_timed_ops(&o,wait_timed,33,44,&b)==YB_EGL_BRIDGE_ARGUMENT && b==owned);
 CHECK(yb_egl_output_bridge_release_timed(&b,UINT64_C(5000000001))==YB_EGL_BRIDGE_ARGUMENT);
 CHECK(b==owned && s.waits==0 && s.deletes==0 && !memcmp(&s.binding,&saved,sizeof(saved)));
 CHECK(yb_egl_output_bridge_release_timed(&b,0)==YB_EGL_BRIDGE_CONSUMER);
 CHECK(s.timeout==0 && s.waits==1 && s.deletes==0 && b==owned);
 CHECK(!memcmp(&s.binding,&saved,sizeof(saved)));
 CHECK(yb_egl_output_bridge_release_timed(&b,123)==YB_EGL_BRIDGE_CONSUMER);
 CHECK(s.timeout==123 && s.waits==2 && s.deletes==0 && b==owned);
 s.done=1;
 CHECK(yb_egl_output_bridge_release_timed(&b,123)==0 && b==NULL);
 CHECK(s.waits==3 && s.deletes==2 && !memcmp(&s.binding,&saved,sizeof(saved)));
 CHECK(yb_egl_output_bridge_release_timed(&b,0)==0);
 CHECK(yb_egl_output_bridge_release_timed(NULL,0)==YB_EGL_BRIDGE_ARGUMENT);
 CHECK(yb_egl_output_bridge_create_with_ops(&o,33,44,&b)==0);
 CHECK(yb_egl_output_bridge_release_timed(&b,0)==YB_EGL_BRIDGE_UNSUPPORTED);
 CHECK(b!=NULL && s.waits==3 && s.deletes==2);
 CHECK(yb_egl_output_bridge_release(&b)==0 && b==NULL);
 return 0;
}
'''
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            harness = path / "test.c"
            harness.write_text(source)
            binary = path / "test"
            subprocess.run([os.environ.get("CC", "cc"), "-std=c11", "-O2",
                            "-Wall", "-Wextra", "-Werror", "-Wconversion",
                            "-Wshadow", "-fsanitize=undefined",
                            "-fno-sanitize-recover=all", "-DYB_EGL_BRIDGE_HOST_ONLY",
                            "-I", str(ROOT), str(harness),
                            str(ROOT / "native_egl_output_bridge.c"), "-o", str(binary)],
                           check=True, capture_output=True)
            subprocess.run([str(binary)], check=True, capture_output=True, timeout=5)


if __name__ == "__main__":
    unittest.main()
