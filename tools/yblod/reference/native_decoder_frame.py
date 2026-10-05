"""Private decoder-native instructions to bounded full-frame C comparison.

Existing manifests verify pixels/baselines only; their instruction configuration
is never used to initialize this path. Caller pins the same-build library/blob.
"""
from contextlib import ExitStack
import ctypes as C
import hashlib
from pathlib import Path
import sys
import native_integration_frame as frame
import native_stage as native

SOURCES=("native_decoder_frame.py","native_decoder_frame_bridge.c","native_decoder_frame_bridge.h",
         "native_dovi_adapter.h",*frame.SOURCES)
ROOT=Path(__file__).resolve().parent

def pins(): return {name:native.digest(ROOT/name) for name in SOURCES}

def compare(library, instructions, instructions_sha256, prepared_manifest, baseline,
            extraction, *, library_sha256, chunk_samples=65536, require_memory_cap=True):
    """Return private evidence only. No public writer or film/config publication."""
    native._integer(chunk_samples,"chunk_samples",1,65536)
    if type(require_memory_cap) is not bool: raise ValueError("explicit memory control required")
    before=frame.memory_snapshot()
    if require_memory_cap and not frame.memory_valid(before): raise ValueError("memory cap required")
    source_pins=pins()
    path=Path(library).resolve(strict=True)
    if native.digest(path)!=library_sha256: raise ValueError("library identity differs")
    lib=C.CDLL(str(path))
    for symbol in ("yb_decoder_frame_bridge_abi_version","yb_integration_abi_version","yb_abi_version"):
        query=getattr(lib,symbol);query.argtypes=[];query.restype=C.c_uint32
        if query()!=1: raise ValueError("ABI differs")
    for symbol,structure in (("yb_integration_sizeof_descriptor",frame.Descriptor),
                             ("yb_integration_sizeof_context",frame.Context),
                             ("yb_integration_sizeof_completion",frame.Completion),
                             ("yb_sizeof_mapping_config",native.Mapping),
                             ("yb_sizeof_nlq_config",native.NLQ)):
        query=getattr(lib,symbol);query.argtypes=[];query.restype=C.c_uint64
        if query()!=C.sizeof(structure): raise ValueError("ABI size differs")
    query=lib.yb_decoder_frame_bridge_sizeof_instructions;query.argtypes=[];query.restype=C.c_uint64
    size=query()
    if not 1<=size<=65536: raise ValueError("instruction size outside diagnostic bound")
    reader=frame.Reader(Path(instructions).parent,Path(instructions).name,size,1,instructions_sha256)
    try: raw=reader.read(size);reader.finish()
    finally: reader.close()
    manifest,verified,specs,input_pins,counts,kind,unchanged=frame.prepare(prepared_manifest,baseline,extraction)
    context=frame.Context()
    # Enable/output values come from the native blob, not manifest metadata.
    # Read only fixed ABI header scalars; C validates them authoritatively.
    if sys.byteorder!="little": raise ValueError("little endian diagnostic required")
    enabled=int.from_bytes(raw[4:8],"little",signed=True)
    depth=int.from_bytes(raw[8:12],"little",signed=True)
    descriptor=frame.Descriptor(1,1,manifest["width"],manifest["height"],depth,enabled)
    descriptor.frame_id[:]=hashlib.sha256(str(verified["identity"]).encode()).digest()
    descriptor.provenance_id[:]=hashlib.sha256(raw).digest()
    blob=C.create_string_buffer(raw)
    init=lib.yb_decoder_frame_bridge_init
    init.argtypes=[C.POINTER(frame.Context),C.POINTER(frame.Descriptor),C.c_void_p,C.c_size_t];init.restype=C.c_int
    if init(C.byref(context),C.byref(descriptor),blob,len(raw)): raise ValueError("native instructions rejected")
    if bool(enabled)!=("el_Y" in specs): raise ValueError("prepared EL consumption differs")
    needs_guide=any(segment.method==1 for component in context.mapping.components
                    for segment in component.segments[:component.pivot_count-1])
    if needs_guide and "guide" not in specs: raise ValueError("decoded MMR requires prepared guide")
    if context.mapping.bit_depth!=manifest["metadata"]["bl_bit_depth"]:
        raise ValueError("prepared BL declaration differs from decoder")
    if enabled and any(n.bit_depth!=manifest["metadata"]["el_bit_depth"] for n in context.nlq):
        raise ValueError("prepared EL declaration differs from decoder")
    # Existing Adapter methods dispatch native chunks; its JSON constructor is
    # deliberately never called.
    adapter=object.__new__(frame.Adapter)
    adapter.lib=lib;adapter.context=context;adapter.descriptor=descriptor;adapter.enabled=bool(enabled)
    u16,i32=C.POINTER(C.c_uint16),C.POINTER(C.c_int32)
    lib.yb_integration_integer.argtypes=[C.POINTER(frame.Context),C.POINTER(C.c_uint8),C.c_int32,C.c_uint64,u16,u16,u16,u16,C.c_uint32,u16,i32,i32,u16]
    lib.yb_integration_integer.restype=C.c_int
    lib.yb_integration_finish.argtypes=[C.POINTER(frame.Context),C.POINTER(frame.Completion)];lib.yb_integration_finish.restype=C.c_int
    lib.yb_integration_reset.argtypes=[C.POINTER(frame.Context)];lib.yb_integration_reset.restype=None
    stages={}
    try:
        for component,channel in enumerate(frame.CHANNELS):
            roles=(["bl_Y",None,None] if component==0 else ["guide" if "guide" in specs else None,"bl_Cb","bl_Cr"])
            roles.append("el_"+channel if enabled else None)
            with ExitStack() as stack:
                def open_role(role):
                    if role is None:return None
                    value=frame.Reader(*specs[role]);stack.callback(value.close);return value
                inputs=[open_role(role) for role in roles]
                saved=[open_role(stage+"_"+channel) for stage,_ in frame.STAGES]
                digests=[hashlib.sha256() for _ in saved]
                for start in range(0,counts[component],chunk_samples):
                    count=min(chunk_samples,counts[component]-start)
                    actual=adapter.process(component,start,[value.read(count) if value else None for value in inputs],count)
                    for generated,expected,digest in zip(actual,saved,digests):
                        if generated!=expected.read(count):raise ValueError("stage byte mismatch")
                        digest.update(generated)
                for value in inputs:
                    if value:value.finish()
                for (stage,_),expected,digest in zip(frame.STAGES,saved,digests):
                    identity=expected.finish()
                    if digest.hexdigest()!=identity:raise ValueError("stage digest mismatch")
                    stages[stage+"_"+channel]=dict(samples=counts[component],byte_exact=True,sha256=identity)
        completion=adapter.finish(counts)
        unchanged()
        if pins()!=source_pins or native.digest(path)!=library_sha256 or native.digest(instructions)!=instructions_sha256:
            raise ValueError("execution inputs changed")
        after=frame.memory_snapshot()
        if require_memory_cap and not frame.memory_valid(before,after):raise ValueError("memory guard failed")
        return dict(status="complete",source_sha256=source_pins,input_sha256=input_pins,
                    library_sha256=library_sha256,instructions_sha256=instructions_sha256,
                    stages=stages,completion=completion,baseline_kind=kind,
                    memory_before=before,memory_after=after,memory_cap_required=require_memory_cap)
    finally:adapter.reset()
