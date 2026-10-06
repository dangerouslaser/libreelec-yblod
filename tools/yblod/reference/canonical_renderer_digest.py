"""Fingerprint private tunnel RGB modulo validated transport ID/checksum bits.

No frames are copied. Source timestamps remain exact comparison keys. A matching
SHA256 is cryptographic evidence, not a literal byte-by-byte comparison claim.
"""
import argparse
import hashlib
import json
import stat
from pathlib import Path
import numpy as np
import compare_renderer_frames as comparator


def canonical_digest(folder):
    if not folder.is_absolute() or folder.resolve()!=folder:
        raise ValueError('Absolute nonsymlink capture directory required')
    paths=[folder/name for name in ('frame.json','metadata.bin','output.rgba')]
    def identity():
        return [(p.stat().st_dev,p.stat().st_ino,p.stat().st_size,
                 p.stat().st_mtime_ns,p.stat().st_ctime_ns) for p in paths]
    before=identity()
    for p,limit in zip(paths,(16384,1048576,comparator.W*comparator.H*4)):
        s=p.lstat()
        if not stat.S_ISREG(s.st_mode) or not 0<s.st_size<=limit:
            raise ValueError('Invalid capture member')
    info,frame,_,_=comparator.load_frame(folder)
    if any(type(info[k]) is not int or info[k]<=0 for k in ('pts','el_pts')):
        raise ValueError('Exact integer source timestamps required')
    packets=comparator.decode_packets(frame)
    first=frame[:4,:,:3].copy().reshape(-1,3)
    payload=hashlib.sha256()
    for index,packet in enumerate(packets):
        normalized=bytearray(packet)
        normalized[1]=0
        normalized[124:128]=comparator.crc32_mpeg2(normalized[:124]).to_bytes(4,'big')
        payload.update(normalized[:124])
        delta=np.unpackbits(np.frombuffer(packet,dtype=np.uint8)^np.frombuffer(normalized,dtype=np.uint8))
        first[index*3072:(index+1)*3072,2]^=np.tile(delta,3)<<4
    image=hashlib.sha256();image.update(first.tobytes())
    for start in range(4,comparator.H,64):
        image.update(frame[start:start+64,:,:3].tobytes())
    metadata=comparator.digest(folder/'metadata.bin').hex()
    if identity()!=before:raise ValueError('Capture changed during fingerprinting')
    return dict(schema='yblod.canonical-tunnel-fingerprint.v1',
        pts=info['pts'],el_pts=info['el_pts'],source_metadata_sha256=metadata,
        canonical_rgb_sha256=image.hexdigest(),canonical_packets_sha256=payload.hexdigest(),
        packet_count=len(packets),crc_and_repetitions_valid=True,
        orientation_unambiguous=True,capture_stat_identity_unchanged=True,
        normalization='Only validated transport update-ID byte and dependent CRC bits; alpha excluded.',
        route={k:info.get(k) for k in ('native','native_planar','direct_packed','batched_planes',
            'immutable_instructions','el_decoder_qsv','el_qsv_map_sequence','el_qsv_native_used')})


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('folder',type=Path)
    print(json.dumps(canonical_digest(parser.parse_args().folder),allow_nan=False))
