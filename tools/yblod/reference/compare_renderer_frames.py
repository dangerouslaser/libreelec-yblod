"""Compare privately captured DV tunnel outputs in bounded row chunks."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import sys
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'accuracy'))
from dvtunnel import crc32_mpeg2, packets_ok, unpack_rgb

W, H = 3840, 2160


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            h.update(block)
    return h.digest()


def load_frame(folder):
    info = json.loads((folder / 'frame.json').read_text())
    if info.get('format') != 'RGBA8 DV tunnel bottom up':
        raise ValueError('Unsupported capture format')
    for field in ('native_planar', 'batched_planes', 'immutable_instructions'):
        if field in info and (type(info[field]) is not int or info[field] not in (0, 1)):
            raise ValueError('Invalid native output route metadata')
    for name in ('pts', 'el_pts'):
        value = info.get(name)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
            raise ValueError('Invalid decoded layer timestamp')
    if not (folder / 'metadata.bin').stat().st_size:
        raise ValueError('Source Dolby metadata is empty')
    if (info['width'], info['height']) != (W, H):
        raise ValueError('Wrong frame size')
    path = folder / 'output.rgba'
    if path.stat().st_size != W * H * 4:
        raise ValueError('Wrong raw frame extent')
    data = np.memmap(path, mode='r', dtype=np.uint8, shape=(H, W, 4))
    possibilities = []
    for flip in (False, True):
        candidate = data[::-1] if flip else data
        y, c = unpack_rgb(candidate[:4, :, 0], candidate[:4, :, 1], candidate[:4, :, 2])
        valid = packets_ok(y, c)
        if valid:
            possibilities.append((candidate, flip, valid))
    if len(possibilities) != 1:
        raise ValueError('Ambiguous or invalid DV packet orientation')
    frame, flipped, valid = possibilities[0]
    return info, frame, flipped, valid


def decode_packets(frame):
    y, c = unpack_rgb(frame[:4, :, 0], frame[:4, :, 1], frame[:4, :, 2])
    yf, cf = y.reshape(-1), c.reshape(-1)
    packets = []
    count = None
    for index in range(4):
        copies = []
        for repeat in range(3):
            start = index * 3072 + repeat * 1024
            yy, cc = yf[start:start+1024], cf[start:start+1024]
            if len(yy) != 1024:
                raise ValueError('Incomplete tunnel metadata region')
            parity = (np.array([int(v >> 1).bit_count() for v in cc]) +
                      np.array([int(v).bit_count() for v in yy])) & 1
            packet = np.packbits(((cc & 1) ^ parity).astype(np.uint8)).tobytes()
            if crc32_mpeg2(packet[:124]) != int.from_bytes(packet[124:], 'big'):
                raise ValueError('Invalid transport packet CRC')
            copies.append(packet)
        if copies[1:] != copies[:1] * 2:
            raise ValueError('Transport packet repetitions differ')
        packet = copies[0]
        if packet[1] >> 4 != packet[1] & 15 or packet[2] != 0:
            raise ValueError('Invalid transport packet header')
        if index and packet[1] != packets[0][1]:
            raise ValueError('Transport update ID differs within packet sequence')
        if index == 0:
            size = int.from_bytes(packet[3:5], 'big')
            if not 1 <= size <= 482:
                raise ValueError('Invalid transport payload size')
            count = 1 if size <= 119 else 1 + (size - 119 + 120) // 121
        expected_type = 0 if count == 1 else 1 if index == 0 else 3 if index + 1 == count else 2
        if packet[0] != expected_type << 6:
            raise ValueError('Invalid transport packet sequence')
        packets.append(packet)
        if len(packets) == count:
            return packets
    raise ValueError('Incomplete transport packet sequence')


def verify_picture_and_payload(pa, pb):
    old, new = decode_packets(pa), decode_packets(pb)
    if len(old) != len(new):
        raise ValueError('Transport packet counts differ')
    expected_xor = np.zeros((4 * W, 3), dtype=np.uint8)
    for index, (a, b) in enumerate(zip(old, new)):
        if a[:1] + a[2:124] != b[:1] + b[2:124]:
            raise ValueError('Transport payload or non-ID header differs')
        bit_delta = np.unpackbits(np.frombuffer(a, dtype=np.uint8) ^ np.frombuffer(b, dtype=np.uint8))
        expected_xor[index*3072:(index+1)*3072, 2] = np.tile(bit_delta, 3) << 4
    actual_xor = (pa[:4, :, :3] ^ pb[:4, :, :3]).reshape(-1, 3)
    if not np.array_equal(actual_xor, expected_xor):
        raise ValueError('Picture differs within metadata rows beyond validated ID/checksum bits')
    for start in range(4, H, 64):
        if not np.array_equal(pa[start:start+64, :, :3], pb[start:start+64, :, :3]):
            raise ValueError('Picture pixels differ outside transport metadata')
    return dict(picture_and_payload_preserved=True, packet_count=len(old),
                permitted_difference='Only validated 4-bit transport update IDs and their CRCs; no picture or payload changes.')


def compare(a, b, require_exact=False, require_picture_and_payload_preserved=False):
    ia, pa, fa, ca = load_frame(a)
    ib, pb, fb, cb = load_frame(b)
    if abs(ia['pts'] - ib['pts']) > 1 or abs(ia['el_pts'] - ib['el_pts']) > 1:
        raise ValueError('Decoded layer timestamps do not match within one microsecond')
    if digest(a / 'metadata.bin') != digest(b / 'metadata.bin'):
        raise ValueError('Source Dolby metadata differs')
    differing_rgb_bytes = 0
    for start in range(0, H, 64):
        end = min(start + 64, H)
        differing_rgb_bytes += int(np.count_nonzero(pa[start:end, :, :3] != pb[start:end, :, :3]))
    if require_exact and differing_rgb_bytes:
        raise ValueError('Output-preservation gate failed: normalized tunnel RGB bytes differ')
    semantic = verify_picture_and_payload(pa, pb) if require_picture_and_payload_preserved else None
    totals = {name: dict(count=0, absolute_sum=0, squared_sum=0, signed_sum=0,
                        maximum=0, changed=0, over_one=0, at_least_four=0,
                        at_least_sixteen=0) for name in ('I', 'P', 'T')}
    for start in range(4, H, 64):
        end = min(start + 64, H)
        ay, ac = unpack_rgb(pa[start:end, :, 0], pa[start:end, :, 1], pa[start:end, :, 2])
        by, bc = unpack_rgb(pb[start:end, :, 0], pb[start:end, :, 1], pb[start:end, :, 2])
        for name, old, new in (('I', ay, by), ('P', ac[:, ::2], bc[:, ::2]),
                               ('T', ac[:, 1::2], bc[:, 1::2])):
            delta = new.astype(np.int32) - old.astype(np.int32)
            absolute = np.abs(delta)
            stats = totals[name]
            stats['count'] += delta.size
            stats['absolute_sum'] += int(absolute.sum(dtype=np.int64))
            stats['squared_sum'] += int((delta.astype(np.int64) ** 2).sum())
            stats['signed_sum'] += int(delta.sum(dtype=np.int64))
            stats['maximum'] = max(stats['maximum'], int(absolute.max()))
            for key, mask in (('changed', absolute != 0), ('over_one', absolute > 1),
                              ('at_least_four', absolute >= 4), ('at_least_sixteen', absolute >= 16)):
                stats[key] += int(np.count_nonzero(mask))
    planes = {}
    for name, stats in totals.items():
        count = stats['count']
        mse = stats['squared_sum'] / count
        planes[name] = dict(count=count, mean_absolute_codes=stats['absolute_sum']/count,
            mean_signed_codes=stats['signed_sum']/count, max_absolute_codes=stats['maximum'],
            rmse_codes=math.sqrt(mse), psnr_db=10*math.log10(4095**2/mse) if mse else None,
            exact_percent=100*(count-stats['changed'])/count,
            over_one_percent=100*stats['over_one']/count,
            at_least_four_percent=100*stats['at_least_four']/count,
            at_least_sixteen_percent=100*stats['at_least_sixteen']/count)
    return dict(schema='yblod.renderer-output-comparison.v1',
        identical_source_layer_timestamps=True, identical_source_metadata=True,
        output_preserved=differing_rgb_bytes == 0,
        picture_and_payload_preservation=semantic,
        differing_tunnel_rgb_bytes=differing_rgb_bytes,
        preservation_scope='All oriented tunnel RGB bytes, including metadata rows; alpha is not transmitted.',
        before=dict(native=ia['native'], direct_packed=ia['direct_packed'],
                    rows_flipped=fa, valid_leading_packets=ca,
                    **{key: ia[key] for key in ('native_planar', 'batched_planes', 'immutable_instructions') if key in ia}),
        after=dict(native=ib['native'], direct_packed=ib['direct_packed'],
                   rows_flipped=fb, valid_leading_packets=cb,
                   **{key: ib[key] for key in ('native_planar', 'batched_planes', 'immutable_instructions') if key in ib}), planes=planes,
        scope='12-bit tunnel code differences between players, not Dolby conformance or display quality.',
        region='Full picture excluding first four metadata rows; letterbox bars remain included.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('before', type=Path)
    parser.add_argument('after', type=Path)
    parser.add_argument('--require-exact', action='store_true',
                        help='Fail unless every oriented tunnel RGB byte is unchanged, including metadata rows.')
    parser.add_argument('--require-picture-and-payload-preserved', action='store_true',
                        help='Require exact picture and payload; allow only validated transport update ID/CRC changes.')
    args = parser.parse_args()
    print(json.dumps(compare(args.before, args.after, args.require_exact,
                             args.require_picture_and_payload_preserved), indent=2, allow_nan=False))
