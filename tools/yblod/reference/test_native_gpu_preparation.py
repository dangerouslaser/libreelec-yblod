"""CPU guards and API structure checks; not a driver-lifecycle execution test."""
import ctypes as C
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3]
ENGINE = ROOT / "engine/experimental"

class Plan(C.Structure):
    _fields_ = [(name, C.c_uint32) for name in ("version", "width", "height", "bl_luma_texture", "bl_chroma_texture", "phase_filter", "chroma_location")] + [(name, C.c_uint8*32) for name in ("frame_id", "guide_contract_id", "phase_contract_id")]

def valid_plan():
    p = Plan(1, 3840, 2160, 1, 2, 2, 1)
    p.frame_id[0], p.guide_contract_id[0], p.phase_contract_id[0] = 1, 2, 3
    return p

class PreparationHostTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        binary = Path(cls.directory.name) / "preparation.so"
        command = ["cc", "-std=c11", "-O2", "-fno-lto", "-fPIC", "-shared", "-Wall", "-Wextra", "-Werror", "-Wconversion", "-Wshadow", "-DYB_GPU_PREPARATION_HOST_ONLY", "-I", str(ROOT/"engine/include"), *shlex.split(os.environ.get("YB_GPU_FRAME_TEST_CFLAGS", "")), str(ENGINE/"native_gpu_preparation.c"), "-o", str(binary)]
        run = subprocess.run(command, capture_output=True, text=True, timeout=30)
        if run.returncode:
            raise RuntimeError(run.stderr)
        cls.lib = C.CDLL(str(binary))
        cls.lib.yb_gpu_preparation_validate_plan.argtypes = [C.POINTER(Plan)]
        cls.lib.yb_gpu_preparation_submit.argtypes = [C.c_void_p, C.POINTER(Plan)]

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def test_explicit_policies_valid(self):
        p = valid_plan()
        for width, height in ((2, 2), (3840, 2160)):
            for phase in (1, 2):
                for location in (0, 1):
                    p.width, p.height, p.phase_filter, p.chroma_location = width, height, phase, location
                    self.assertEqual(self.lib.yb_gpu_preparation_validate_plan(C.byref(p)), 0)

    def test_geometry_policy_object_reject_atomic(self):
        for field, value in (("version", 0), ("width", 0), ("width", 3842), ("width", 3), ("height", 2162), ("height", 3), ("bl_luma_texture", 0), ("bl_chroma_texture", 0), ("bl_chroma_texture", 1), ("phase_filter", 0), ("phase_filter", 3), ("chroma_location", 2)):
            with self.subTest(field=field, value=value):
                p = valid_plan()
                setattr(p, field, value)
                before = bytes(p)
                self.assertEqual(self.lib.yb_gpu_preparation_validate_plan(C.byref(p)), 1)
                self.assertEqual(bytes(p), before)

    def test_nonzero_tokens_and_alignment(self):
        for name in ("frame_id", "guide_contract_id", "phase_contract_id"):
            p = valid_plan()
            getattr(p, name)[0] = 0
            self.assertEqual(self.lib.yb_gpu_preparation_validate_plan(C.byref(p)), 1)
        self.assertEqual(self.lib.yb_gpu_preparation_validate_plan(None), 1)
        raw = C.create_string_buffer(C.sizeof(Plan)+1)
        self.assertEqual(self.lib.yb_gpu_preparation_validate_plan(C.cast(C.byref(raw, 1), C.POINTER(Plan))), 1)

    def test_host_route_no_dispatch(self):
        p = valid_plan()
        self.assertEqual(self.lib.yb_gpu_preparation_submit(None, C.byref(p)), 3)
        p.phase_filter = 0
        self.assertEqual(self.lib.yb_gpu_preparation_submit(None, C.byref(p)), 1)

    def test_no_egl_or_plane_readback_one_fence(self):
        source = (ENGINE/"native_gpu_preparation.c").read_text()
        submit = source.split("int yb_gpu_preparation_submit", 1)[1].split("int yb_gpu_preparation_finish", 1)[0]
        self.assertEqual(submit.count("g->DispatchCompute("), 2)
        self.assertEqual(submit.count("g->FenceSync("), 1)
        self.assertNotIn("ClientWaitSync(", submit)
        self.assertNotIn("GetBufferSubData(", submit)
        self.assertNotIn("egl", source)
        self.assertNotIn("GetTexImage", source)
        self.assertIn("GetBufferSubData(GL_SHADER_STORAGE_BUFFER,0,12,status)", source)
        self.assertIn("if(b->pending)return YB_GPU_BACKEND_BUSY", source)
        self.assertIn("timeout>UINT64_C(5000000000)", source)
