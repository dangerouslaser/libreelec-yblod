"""Synthetic lossless CPU transport tests; no hardware surface ownership claim."""
import ctypes as C
import hashlib
import json
from pathlib import Path
import resource
import shutil
import struct
import subprocess
import tempfile
import time
import unittest

ROOT=Path(__file__).resolve().parent
U16=C.POINTER(C.c_uint16)


class Surface(C.Structure):
    _fields_=[("data",C.POINTER(C.c_uint8)),("bytes",C.c_uint64),("width",C.c_uint64),
              ("height",C.c_uint64),("stride",C.c_uint64),("layout",C.c_uint32),
              ("storage_bits",C.c_uint32),("native_depth",C.c_uint32),("fractional_bits",C.c_uint32)]


class NativeY416Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not shutil.which("cc"):raise unittest.SkipTest("host C compiler unavailable")
        cls.temporary=tempfile.TemporaryDirectory();root=Path(cls.temporary.name)
        library=root/"liby416.so"
        subprocess.run(["cc","-std=c11","-O2","-fPIC","-shared","-Wall","-Wextra","-Werror",
                        "-Wconversion","-Wshadow",str(ROOT/"native_y416.c"),"-o",str(library)],check=True,capture_output=True)
        cls.library=C.CDLL(str(library));cls.fn=cls.library.yb_y416_unpack_rows
        cls.fn.argtypes=[C.POINTER(Surface),C.c_uint64,C.c_uint64,U16,U16,U16,U16,C.c_uint64]
        cls.fn.restype=C.c_int
        size=cls.library.yb_y416_sizeof_surface;size.restype=C.c_uint64
        assert size()==C.sizeof(Surface)

    @classmethod
    def tearDownClass(cls):cls.temporary.cleanup()

    def fixture(self,width=3,height=3,padding=5,unaligned=False):
        stride=width*8+padding;footprint=(height-1)*stride+width*8
        data=bytearray([0xa5]*footprint);pixels=[]
        for y in range(height):
            row=[]
            for x in range(width):
                pixel=((x+7*y)*17%65536,32768+(x+3*y)%64,65535-(x+5*y), (0,65280,65535)[(x+y)%3])
                data[y*stride+x*8:y*stride+x*8+8]=struct.pack("<4H",*pixel);row.append(pixel)
            pixels.append(row)
        offset=1 if unaligned else 0
        owner=C.create_string_buffer(bytes(offset)+data)
        pointer=C.cast(C.byref(owner,offset),C.POINTER(C.c_uint8))
        surface=Surface(pointer,footprint,width,height,stride,1,16,10,6)
        return surface,owner,pixels

    def output(self,count):return [(C.c_uint16*count)(*([0xdead]*count)) for _ in range(4)]

    def test_literal_little_endian_word_order_and_all_bits(self):
        raw=bytes((0x34,0x12,0xcd,0xab,0xff,0xff,0x01,0x80))
        owner=C.create_string_buffer(raw);surface=Surface(C.cast(owner,C.POINTER(C.c_uint8)),8,1,1,8,1,16,10,6)
        outputs=self.output(1)
        self.assertEqual(self.fn(C.byref(surface),0,1,*outputs,1),0)
        self.assertEqual([p[0] for p in outputs],[0x1234,0xabcd,65535,0x8001])

    def test_all_low_bits_overshoot_and_alpha_preserved(self):
        pixels=[(32768+n,65472+n,n,(65280+n)%65536) for n in range(64)]
        raw=b"".join(struct.pack("<4H",*p) for p in pixels)
        owner=C.create_string_buffer(raw);surface=Surface(C.cast(owner,C.POINTER(C.c_uint8)),len(raw),64,1,len(raw),1,16,10,6)
        outputs=self.output(64)
        self.assertEqual(self.fn(C.byref(surface),0,1,*outputs,64),0)
        self.assertEqual([list(p) for p in outputs],list(map(list,zip(*pixels))))

    def test_odd_dimensions_unaligned_input_pitch_and_partial_region(self):
        surface,owner,pixels=self.fixture(3,3,5,True);before=owner.raw
        outputs=self.output(6)
        self.assertEqual(self.fn(C.byref(surface),1,2,*outputs,6),0)
        expected=[p for row in pixels[1:] for p in row]
        self.assertEqual([list(p) for p in outputs],list(map(list,zip(*expected))))
        self.assertEqual(owner.raw,before)

    def test_invalid_metadata_region_counts_leave_outputs_unchanged(self):
        surface,owner,_=self.fixture();outputs=self.output(9)
        trials=[]
        for field,value in (("layout",0),("storage_bits",12),("native_depth",12),("fractional_bits",0),
                            ("bytes",surface.bytes-1),("stride",23),("stride",(1<<64)-1),("width",0),
                            ("width",8193),("height",0),("height",8193)):
            invalid=Surface.from_buffer_copy(surface);setattr(invalid,field,value);trials.append((invalid,0,3,9))
        trials.extend((surface,first,rows,count) for first,rows,count in ((0,0,0),(3,1,3),((1<<64)-1,1,3),(0,(1<<64)-1,9),(0,3,8),(0,3,10)))
        for invalid,first,rows,count in trials:
            self.assertNotEqual(self.fn(C.byref(invalid),first,rows,*outputs,count),0)
            self.assertEqual([list(p) for p in outputs],[[0xdead]*9]*4)
        self.assertNotEqual(self.fn(None,0,3,*outputs,9),0)

    def test_aliases_null_and_unaligned_outputs_fail_before_any_write(self):
        surface,owner,_=self.fixture();outputs=self.output(9);saved=owner.raw
        candidates=(None,outputs[0],C.cast(surface.data,U16),C.cast(C.byref(surface),U16))
        for bad in candidates:
            pointers=[C.cast(p,U16) for p in outputs];pointers[3]=bad
            self.assertNotEqual(self.fn(C.byref(surface),0,3,*pointers,9),0)
            self.assertEqual([list(p) for p in outputs],[[0xdead]*9]*4);self.assertEqual(owner.raw,saved)
        byteowner=C.create_string_buffer(19);pointers=[C.cast(p,U16) for p in outputs]
        pointers[3]=C.cast(C.byref(byteowner,1),U16)
        self.assertNotEqual(self.fn(C.byref(surface),0,3,*pointers,9),0)
        self.assertEqual([list(p) for p in outputs],[[0xdead]*9]*4)

    def test_pointer_extent_overflow_and_chunk_limit_fail_closed(self):
        surface,owner,_=self.fixture();outputs=self.output(9)
        invalid=Surface.from_buffer_copy(surface);invalid.data=C.cast(C.c_void_p((1<<(C.sizeof(C.c_void_p)*8))-8),C.POINTER(C.c_uint8))
        self.assertNotEqual(self.fn(C.byref(invalid),0,3,*outputs,9),0)
        invalid=Surface.from_buffer_copy(surface);invalid.width=8192;invalid.height=9;invalid.stride=8192*8;invalid.bytes=9*8192*8
        self.assertNotEqual(self.fn(C.byref(invalid),0,9,*outputs,73728),0)
        self.assertEqual([list(p) for p in outputs],[[0xdead]*9]*4)


def verify_archive(manifest_path,destination):
    """Stream every word of saved synthetic surfaces; no GPU or file rewrite."""
    manifest=json.loads(Path(manifest_path).read_text())
    cases=manifest["cases"]
    if type(cases) is not list or not 1<=len(cases)<=32:raise ValueError("bounded case list required")
    names=[case["name"] for case in cases]
    if any(type(name) is not str or not name for name in names) or len(set(names))!=len(names):
        raise ValueError("unique nonempty case names required")
    for case in cases:
        for key in ("sha256","source_report_sha256"):
            value=case[key]
            if type(value) is not str or len(value)!=64 or any(c not in "0123456789abcdef" for c in value):raise ValueError("strict SHA required")
    started=time.monotonic();results={}
    NativeY416Tests.setUpClass()
    try:
        for case in cases:
            width,height=case["width"],case["height"]
            if any(type(v) is not int or not 1<=v<=8192 for v in (width,height)):raise ValueError("invalid dimensions")
            path=Path(case["path"]);initial=path.stat()
            if initial.st_size!=width*height*8:raise ValueError("archive byte count mismatch")
            digest=hashlib.sha256();samples=0
            #16rows at4K fit below65536 samples; fewer for larger widths.
            rows_per=min(16,65536//width)
            with path.open("rb") as handle:
                for first in range(0,height,rows_per):
                    rows=min(rows_per,height-first);count=rows*width
                    raw=handle.read(count*8)
                    if len(raw)!=count*8:raise ValueError("archive truncated")
                    digest.update(raw)
                    owner=C.create_string_buffer(raw)
                    surface=Surface(C.cast(owner,C.POINTER(C.c_uint8)),len(raw),width,rows,width*8,1,16,10,6)
                    outputs=[(C.c_uint16*count)() for _ in range(4)]
                    status=NativeY416Tests.fn(C.byref(surface),0,rows,*outputs,count)
                    if status:raise ValueError("native archive chunk rejected")
                    expected=struct.unpack("<"+str(count*4)+"H",raw)
                    for channel in range(4):
                        if tuple(outputs[channel])!=expected[channel::4]:raise ValueError("native raw word mismatch")
                    samples+=count
                if handle.read(1):raise ValueError("archive extra bytes")
            after=path.stat()
            if (initial.st_ino,initial.st_size,initial.st_mtime_ns,initial.st_ctime_ns)!=(after.st_ino,after.st_size,after.st_mtime_ns,after.st_ctime_ns):
                raise ValueError("archive changed while reading")
            if digest.hexdigest()!=case["sha256"]:raise ValueError("archive source SHA mismatch")
            if samples!=width*height:raise ValueError("incomplete archive scan")
            results[case["name"]]={"size":[width,height],"bytes":samples*8,"source_sha256":digest.hexdigest(),
                                   "pixels":samples,"word_comparisons":samples*4,"all_words_exact":True,
                                   "source_report_sha256":case["source_report_sha256"]}
    finally:NativeY416Tests.tearDownClass()
    report={"schema":"yblod.native-y416-archive-validation.v1","status":"complete",
            "scope":"lossless CPU unpack of previously saved synthetic hardware surfaces; no processing/scaler/fence accuracy claim",
            "source_sha256":{name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest()
                             for name in ("native_y416.c","native_y416.h",Path(__file__).name)},
            "declared_layout":"LE16 U/Y/V/A","declared_colour_significance":"native10 Q6 current-route convention; alpha unscaled",
            "cases":results,"elapsed_seconds":time.monotonic()-started,
            "process_peak_rss_kib":resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            "rss_units":"KiB on Linux; bytes on Darwin; process lifetime includes compile/test harness, not playback",
            "total_word_comparisons":sum(v["word_comparisons"] for v in results.values()),
            "no_hardware_jobs":True}
    with Path(destination).open("x") as handle:json.dump(report,handle,indent=2);handle.write("\n")
    return report


class NativeY416ArchiveTests(unittest.TestCase):
    def test_archive_all_words_and_hash_fail_closed(self):
        if not shutil.which("cc"):self.skipTest("host C compiler unavailable")
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);source=root/"saved.y416"
            raw=b"".join(struct.pack("<4H",32768+n,65472+n,n,65535-n) for n in range(63))
            source.write_bytes(raw)
            case=dict(name="synthetic",path=str(source),width=7,height=9,
                      sha256=hashlib.sha256(raw).hexdigest(),source_report_sha256="a"*64)
            manifest=root/"manifest.json";manifest.write_text(json.dumps(dict(cases=[case])))
            report=verify_archive(manifest,root/"passed.json")
            self.assertEqual(report["total_word_comparisons"],252)
            self.assertTrue(report["cases"]["synthetic"]["all_words_exact"])
            self.assertNotIn(str(source),json.dumps(report))
            case["sha256"]="b"*64;manifest.write_text(json.dumps(dict(cases=[case])))
            with self.assertRaisesRegex(ValueError,"SHA mismatch"):verify_archive(manifest,root/"failed.json")
            self.assertFalse((root/"failed.json").exists())


if __name__=="__main__":
    import sys
    if len(sys.argv)==4 and sys.argv[1]=="--archive":verify_archive(sys.argv[2],sys.argv[3])
    else:unittest.main()
