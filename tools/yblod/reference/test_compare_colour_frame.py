import copy
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest import mock

import compare_colour_frame as tool


class CompareColourTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name);self.new=self.root/"new";self.old=self.root/"old"
        self.new.mkdir();self.old.mkdir()
        self.identity=dict(frame_id="a"*64+":2296",pts=95762,time_base=[1,1000])
        self.targets=dict(target_ycc=[[1.0,0.0,0.0],[0.0,1.0,0.0],[0.0,0.0,1.0]],target_lms=[[1.0,0.0,0.0],[0.0,1.0,0.0],[0.0,0.0,1.0]],target_offset=[0.0,.5,.5])
        provenance=dict(rpu_json_sha256="b"*64)
        cfg=dict(schema="yblod.colour-frame-config.v1",source_association="verified-extracted-rpu",source_identity=self.identity,
                 source_provenance=provenance,source_dm={},pq_policy="extend-positive-negative-to-zero",code_scale=4096,
                 chroma_expansion="bilinear-left-diagnostic",active_rectangle=[0,0,4,4],outside_codes=[0,2048,2048],**self.targets)
        self.a=dict(schema="yblod.colour-frame-result.v1",status="complete",width=4,height=4,identity=self.identity,configuration=cfg,source_provenance=provenance,stages={})
        self.b=dict(schema="yblod.output-reference.v1",status="complete",width=4,height=4,identity=self.identity,
                    source_dm={},rpu_sha256="b"*64,policy="direct",chroma_expansion="bilinear-left-edge-replicated-float64",active_rectangle=[0,0,4,4],stages={},**self.targets)
        self.pixels=[(100+x,200+x,300+x) for y in range(4) for x in range(4)]
        for folder,report,isnew in ((self.new,self.a,True),(self.old,self.b,False)):
            self.write_pixels(folder,report,self.pixels,isnew)
        self.save()

    def write_pixels(self,folder,report,pixels,isnew):
        raw=struct.pack("<48H",*(v for pixel in pixels for v in pixel));packed=bytearray()
        for index,pixel in enumerate(pixels):
            x=index%4;chroma=pixels[index-x%2][1 if x%2==0 else 2];intensity=pixel[0]
            packed.extend((chroma>>4,intensity>>4,(intensity&15)|((chroma&15)<<4)))
        for name,data in (("transport_ipt444.u16le",raw),("unembedded_tunnel.rgb8",packed)):
            (folder/name).write_bytes(data)
            record=dict(file=name,sha256=tool.sha(folder/name))
            record.update(dict(bytes=len(data)) if isnew else dict(shape=[4,4,3]))
            report["stages"][name if isnew else name.split(".")[0]]=record

    def save(self):
        (self.new/"output.json").write_text(json.dumps(self.a));(self.old/"output.json").write_text(json.dumps(self.b))

    def test_exact_matching_raw_and_packed_counts(self):
        result=tool.compare(self.new,self.old)
        self.assertTrue(result["packed_all_frame_byte_exact"])
        self.assertEqual(result["comparisons"]["raw_new_minus_old"]["P"]["samples"],16)
        self.assertEqual(result["comparisons"]["packed_new_minus_old"]["P"]["samples"],8)
        self.assertEqual(result["comparisons"]["packed_new_minus_old"]["I"]["changed_samples"],0)
        self.assertNotIn("source_dm",result)

    def test_signed_differences_no_fitting(self):
        pixels=[(a+1,b-2,c+3) for a,b,c in self.pixels]
        self.write_pixels(self.new,self.a,pixels,True);self.save()
        result=tool.compare(self.new,self.old)
        for label in ("raw_new_minus_old","packed_new_minus_old"):
            for component,delta in (("I",1),("P",-2),("T",3)):
                stats=result["comparisons"][label][component]
                self.assertEqual(stats["signed_error_histogram"],[dict(error=delta,count=stats["samples"])])
                self.assertEqual(stats["mean_absolute_codes"],abs(delta))

    def test_policy_identity_rpu_dimensions_and_target_rejected(self):
        original=copy.deepcopy(self.a)
        mutations=(lambda v:v.update(width=4.0),lambda v:v["configuration"].update(code_scale=True),
                   lambda v:v["configuration"].update(source_association="declared"),
                   lambda v:v["configuration"].update(pq_policy="reject-outside-unit"),
                   lambda v:v["configuration"].update(active_rectangle=[0,0,2,4]),
                   lambda v:v["configuration"]["source_provenance"].update(rpu_json_sha256="c"*64),
                   lambda v:v["configuration"]["target_offset"].__setitem__(0,1.0),
                   lambda v:v["identity"].update(pts=95763),lambda v:v["identity"].update(time_base=[1.0,1000]))
        for mutate in mutations:
            self.a=copy.deepcopy(original);mutate(self.a);self.save()
            with self.assertRaises(ValueError):tool.compare(self.new,self.old)

    def test_file_hash_size_shape_path_and_codes_fail_closed(self):
        raw=self.new/"transport_ipt444.u16le";original=raw.read_bytes()
        for payload in (original[:-2],original+b"\0\0",b"\0\x10"+original[2:]):
            raw.write_bytes(payload)
            with self.assertRaises(ValueError):tool.compare(self.new,self.old)
        raw.write_bytes(b"\0\x10"+original[2:]);self.a["stages"]["transport_ipt444.u16le"]["sha256"]=tool.sha(raw);self.save()
        with self.assertRaises(ValueError):tool.compare(self.new,self.old)
        raw.write_bytes(original);self.a["stages"]["transport_ipt444.u16le"]["sha256"]=tool.sha(raw)
        self.a["stages"]["transport_ipt444.u16le"]["file"]="../outside";self.save()
        with self.assertRaises(ValueError):tool.compare(self.new,self.old)

    def test_packing_contract_rejected_even_valid_file_hash(self):
        packed=self.new/"unembedded_tunnel.rgb8";raw=bytearray(packed.read_bytes());raw[1]^=1;packed.write_bytes(raw)
        self.a["stages"]["unembedded_tunnel.rgb8"]["sha256"]=tool.sha(packed);self.save()
        with self.assertRaisesRegex(ValueError,"packed/raw"):tool.compare(self.new,self.old)

    def test_capture_args_pair_and_ce_word_reversal_decode(self):
        with self.assertRaises(ValueError):tool.compare(self.new,self.old,capture="missing")
        # LogicalcaptureGBR encodes I100/C200, reverse64bitwords on disk.
        logical=bytes((100>>4,(100&15)|((200&15)<<4),200>>4))*8
        disk=b"".join(logical[i:i+8][::-1] for i in range(0,len(logical),8))
        self.assertEqual(list(tool._decode(disk,True)),[(100,200)]*8)

    def test_json_duplicates_nonfinite_and_preparse_pin(self):
        path=self.root/"metadata.json"
        for raw in ('{"field":1,"field":2}', '{"field":NaN}', '{"field":Infinity}', '{"field":-Infinity}'):
            path.write_text(raw)
            with self.assertRaises(ValueError):tool._pinned_json(path)
        path.write_text('{"field":1}')
        with mock.patch.object(tool,"sha",return_value="f"*64):
            with self.assertRaisesRegex(ValueError,"changed during load"):tool._pinned_json(path)


if __name__=="__main__":unittest.main()
