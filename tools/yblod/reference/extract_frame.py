#!/usr/bin/env python3
"""Extract one P7 frame's native layers and matching RPU by exact source PTS.

Uses FFmpeg for software decoding and dovi_tool for lossless demux/RPU parsing.
No resizing, chroma repositioning, range conversion or DV rendering is performed.
The result is an extraction bundle, NOT a prepared composer input manifest.
"""
import argparse
from array import array
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

CRA_WINDOW_POLICY = "drop-complete-initial-CRA-RASL-pictures-keep-RADL-v2"
CRA_WINDOW_EVIDENCE = "https://github.com/FFmpeg/FFmpeg/blob/n6.1.1/libavcodec/hevcdec.c#L2791"


def digest(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def save_json(path, value):
    with path.open("x") as handle:
        json.dump(value, handle, indent=2, allow_nan=False)
        handle.write("\n")


def unhex_dump(text):
    return bytes.fromhex("".join(line.split(":", 1)[1].split("  ")[0].replace(" ", "")
                                 for line in text.splitlines() if ":" in line))


def length_prefixed_nals(data, length_size):
    offset = 0
    units = []
    while offset < len(data):
        if offset + length_size > len(data):
            raise ValueError("truncated NAL length")
        size = int.from_bytes(data[offset:offset + length_size], "big")
        offset += length_size
        if size < 2 or offset + size > len(data):
            raise ValueError("invalid NAL size")
        units.append(data[offset:offset + size])
        offset += size
    return units


def annexb_nals(data):
    starts = list(re.finditer(b"\x00\x00(?:\x00)?\x01", data))
    if not starts or any(data[:starts[0].start()]):
        raise ValueError("not an Annex B stream")
    units = []
    for index, start in enumerate(starts):
        end = starts[index + 1].start() if index + 1 < len(starts) else len(data)
        unit = data[start.end():end]
        if len(unit) < 2:
            raise ValueError("short Annex B NAL")
        units.append(unit)
    return units


def annexb_file(path, chunk_size=1024 * 1024):
    """Stream NALs with only one unfinished unit plus a chunk in memory.

    Do not retain a whole compressed movie and a second list of copied NALs
    while launching a decoder. Preserve exact start-code/trailing-zero rules
    used by annexb_nals, including delimiters crossing read boundaries.
    """
    if chunk_size < 4:
        raise ValueError("Annex B chunk must hold a start code")
    buffer = b""
    found = False
    with Path(path).open("rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            buffer += chunk
            starts = list(re.finditer(b"\x00\x00(?:\x00)?\x01", buffer))
            if starts:
                if not found and any(buffer[:starts[0].start()]):
                    raise ValueError("not an Annex B stream")
                found = True
                for a, b in zip(starts, starts[1:]):
                    unit = buffer[a.end():b.start()]
                    if len(unit) < 2:
                        raise ValueError("short Annex B NAL")
                    yield unit
                buffer = buffer[starts[-1].start():]
            elif not found and any(buffer):
                # A delimiter may end in the next chunk, so defer validation.
                if not chunk:
                    raise ValueError("not an Annex B stream")
            if not chunk:
                if not found:
                    raise ValueError("not an Annex B stream")
                start = re.match(b"\x00\x00(?:\x00)?\x01", buffer)
                unit = buffer[start.end():]
                if len(unit) < 2:
                    raise ValueError("short Annex B NAL")
                yield unit
                break


def nal_type(unit):
    if len(unit) < 2:
        raise ValueError("short NAL header")
    return (unit[0] >> 1) & 63


def packet_vcl_matches(actual, expected):
    # FFmpeg's raw-HEVC parser may assign the leading zero of the next 4-byte
    # start code to this packet as Annex B trailing_zero_8bits. Full-stream VCL
    # equality is checked separately, without this boundary accommodation.
    return len(actual) == len(expected) and all(
        a.rstrip(b"\0") == b.rstrip(b"\0") for a, b in zip(actual, expected))


def layer_associations(units, hash_rpus=False):
    """Associate wrapped EL/RPU units with the preceding BL first slice.

    Indices are CODED picture indices, never display-frame numbers. EL and RPU
    must follow their BL, verified again against the exact target packet.
    Missing EL/RPU frames are recorded, never replaced by an assumed ordinal.
    """
    current = -1
    enhancements, instructions, rpus = [], [], []
    for unit in units:
        kind = nal_type(unit)
        if kind < 32:
            if len(unit) < 3:
                raise ValueError("short BL slice")
            if unit[2] & 128:
                current += 1
        elif kind == 63:
            inner = unit[2:]
            if nal_type(inner) < 32:
                if len(inner) < 3 or current < 0:
                    raise ValueError("EL without corresponding BL")
                if inner[2] & 128:
                    enhancements.append(current)
        elif kind == 62:
            if current < 0:
                raise ValueError("RPU before first BL")
            instructions.append(current)
            rpus.append(hashlib.sha256(unit[2:]).digest() if hash_rpus else unit[2:])
    for association in (enhancements, instructions):
        if len(set(association)) != len(association):
            raise ValueError("multiple EL frames/RPUs associated with one BL")
    return current + 1, enhancements, instructions, rpus


def frame_vcl(units, index):
    """Count first-slice flags, returning all VCL NALs in the selected frame."""
    current = -1
    selected = []
    for unit in units:
        if nal_type(unit) >= 32:
            continue
        if len(unit) < 3:
            raise ValueError("short VCL NAL")
        if unit[2] & 128:
            current += 1
        elif current < 0:
            raise ValueError("VCL stream starts without a first slice")
        if current == index:
            selected.append(unit)
    if not selected:
        raise ValueError("selected frame has no VCL data")
    return selected, current + 1


def last_random_access(units, target_index, allowed_types=(19, 20, 21)):
    current, access = -1, None
    for unit in units:
        kind = nal_type(unit)
        if kind < 32 and len(unit) >= 3 and unit[2] & 128:
            current += 1
            if current > target_index:
                break
            if kind in allowed_types:
                access = current
    if access is None:
        raise ValueError("no preceding supported random-access picture")
    return access


def picture_nal_types(units):
    """Classify complete coded pictures, rejecting mixed/missing first slices."""
    pictures = []
    temporal_id = None
    for unit in units:
        kind = nal_type(unit)
        if kind >= 32:
            continue
        if len(unit) < 3 or unit[0] & 128 or ((unit[0] & 1) << 5 | unit[1] >> 3):
            raise ValueError("invalid or multilayer VCL picture header")
        if not unit[1] & 7:
            raise ValueError("invalid VCL temporal ID")
        if unit[2] & 128:
            pictures.append(kind)
            temporal_id = unit[1] & 7
        elif not pictures:
            raise ValueError("VCL picture starts without a first slice")
        elif kind != pictures[-1] or unit[1] & 7 != temporal_id:
            raise ValueError("picture contains mixed VCL NAL types or temporal IDs")
    if not pictures:
        raise ValueError("no coded pictures")
    return pictures


def random_access_plan(picture_types, target_index, max_window_frames):
    """Start at IDR/CRA; exclude only the initial CRA's leading RASL group.

    HEVC RASL_N/RASL_R are types 8/9; RADL_N/RADL_R are 6/7. RASL pictures
    associated with a random-access CRA are not decodable without the earlier
    reference pictures. FFmpeg 6.1.1 hevcdec.c:2791-2803 skips their first slice;
    2812-2814 can then report the remaining slices as missing their first slice.
    Remove complete pictures before decoding, not errors after decoding. Later
    CRA leading pictures are retained because decoding is already established.
    """
    if not 0 <= target_index < len(picture_types):
        raise ValueError("target coded picture is out of range")
    candidates = [i for i in range(target_index + 1) if picture_types[i] in (19, 20, 21)]
    for start in reversed(candidates):
        if target_index - start + 1 > max_window_frames:
            break
        dropped = []
        for i in range(start + 1, target_index + 1):
            kind = picture_types[i]
            if kind not in (6, 7, 8, 9):
                break
            if kind in (8, 9):
                if picture_types[start] != 21:
                    raise ValueError("RASL picture associated with an IDR is invalid")
                dropped.append(i)
        if target_index in dropped:
            continue
        return {"start": start, "target": target_index, "discarded": dropped,
                "access_nal_type": picture_types[start], "policy": CRA_WINDOW_POLICY}
    raise ValueError("target requires an earlier self-contained IDR/CRA within --max-window-frames; initial-CRA RASL cannot be recovered")


def parameter_set_discard_evidence(units, kept, state, source_index):
    """Permit discarding only byte-identical repetitions of retained sets.

    Keep only the latest NAL per VPS/SPS/PPS type, not an ever-growing set of
    previously seen hashes: an older definition may have been overwritten.
    This deliberately rejects some safe multi-ID cases rather than guessing
    parameter-set IDs or retaining a stale definition across a state change.
    """
    evidence = []
    for unit in units:
        kind = nal_type(unit)
        if not kept and kind in (36, 37):
            raise ValueError("cannot discard a leading RASL packet carrying a sequence boundary")
        if kind not in (32, 33, 34):
            continue
        if kept:
            state[kind] = (unit, source_index)
        else:
            previous = state.get(kind)
            if previous is None or unit != previous[0]:
                raise ValueError("cannot discard a leading RASL packet carrying new or changed parameter sets")
            evidence.append({"nal_type": kind, "sha256": hashlib.sha256(unit).hexdigest(),
                             "identical_to_retained_source_packet_index": previous[1]})
    return evidence


def write_picture_window(source, destination, packets, picture_types, plan, source_indices):
    """Copy complete retained packets and record the rewritten byte mapping.

    A maximum-sized input packet is still required in memory, but neither the
    whole window nor movie is retained. Packet bytes and source VCLs are never
    re-encoded. Parameter sets in discarded pictures must repeat the latest
    retained set byte-for-byte; new/changed sets and sequence boundaries fail.
    """
    start, target = plan["start"], plan["target"]
    discarded = set(plan["discarded"])
    records, offset, previous_end, parameter_state = [], 0, None, {}
    with Path(source).open("rb") as src, Path(destination).open("xb") as dst:
        for i in range(start, target + 1):
            position, size = int(packets[i]["pos"]), int(packets[i]["size"])
            if position < 0 or not 0 < size <= 64 * 1024 * 1024 or (previous_end is not None and position != previous_end):
                raise ValueError("decode-window packets must be contiguous, positive, and at most 64 MiB each")
            src.seek(position)
            data = src.read(size)
            if len(data) != size:
                raise ValueError("truncated decode-window packet")
            units = annexb_nals(data)
            if picture_nal_types(units) != [picture_types[i]]:
                raise ValueError("demuxed packet must contain exactly one consistently typed coded picture")
            types = {nal_type(unit) for unit in units}
            if i == start and not {32, 33, 34}.issubset(types):
                raise ValueError("random-access picture is not self-contained (VPS/SPS/PPS required)")
            kept = i not in discarded
            redundant_sets = parameter_set_discard_evidence(units, kept, parameter_state, source_indices[i])
            records.append({"layer_coded_index": i, "source_packet_index": source_indices[i],
                            "source_byte": position, "size": size, "nal_type": picture_types[i],
                            "sha256": hashlib.sha256(data).hexdigest(),
                            "window_byte": offset if kept else None,
                            "discarded_redundant_parameter_sets": redundant_sets,
                            "action": "copy" if kept else "discard_initial_CRA_RASL"})
            if kept:
                dst.write(data)
                offset += size
            previous_end = position + size
    if not records or records[-1]["window_byte"] is None:
        raise ValueError("target picture must remain in decode window")
    return {"policy": plan["policy"], "evidence": CRA_WINDOW_EVIDENCE,
            "access_nal_type": plan["access_nal_type"], "packets": records,
            "discarded_source_packet_indices": [r["source_packet_index"] for r in records if r["window_byte"] is None],
            "target_window_byte": records[-1]["window_byte"], "size": offset}


def verify_picture_window(source, window, mapping):
    """Reassemble the saved window checksum from exact retained source packets."""
    records = mapping["packets"]
    if mapping["policy"] not in (CRA_WINDOW_POLICY, "drop-complete-initial-CRA-RASL-pictures-keep-RADL-v1") or not records:
        raise ValueError("unsupported or empty decode-window mapping")
    types = [r["nal_type"] for r in records]
    plan = random_access_plan(types, len(types) - 1, len(types))
    if plan["start"] != 0 or [i for i, r in enumerate(records) if r["window_byte"] is None] != plan["discarded"]:
        raise ValueError("decode-window mapping does not reproduce its RASL policy")
    expected, offset, previous_end, parameter_state = hashlib.sha256(), 0, None, {}
    with Path(source).open("rb") as handle:
        for i, record in enumerate(records):
            position, size = record["source_byte"], record["size"]
            if position < 0 or not 0 < size <= 64 * 1024 * 1024 or (previous_end is not None and position != previous_end):
                raise ValueError("invalid mapped source packet interval")
            if i and (record["layer_coded_index"] != records[i - 1]["layer_coded_index"] + 1
                      or record["source_packet_index"] <= records[i - 1]["source_packet_index"]):
                raise ValueError("mapped source picture indices are not ordered")
            handle.seek(position)
            data = handle.read(size)
            if len(data) != size or hashlib.sha256(data).hexdigest() != record["sha256"]:
                raise ValueError("mapped source packet changed")
            units = annexb_nals(data)
            if picture_nal_types(units) != [record["nal_type"]]:
                raise ValueError("mapped source picture type changed")
            evidence = parameter_set_discard_evidence(units, record["window_byte"] is not None,
                                                       parameter_state, record["source_packet_index"])
            if evidence != record.get("discarded_redundant_parameter_sets", []):
                raise ValueError("discarded parameter-set evidence does not match retained source state")
            if record["window_byte"] is None:
                if record["action"] != "discard_initial_CRA_RASL":
                    raise ValueError("invalid mapped discard action")
            else:
                if record["window_byte"] != offset or record["action"] != "copy":
                    raise ValueError("invalid rewritten packet position")
                expected.update(data)
                offset += size
            previous_end = position + size
    if (offset != mapping["size"] or Path(window).stat().st_size != offset
            or expected.hexdigest() != digest(window)
            or mapping["target_window_byte"] != records[-1]["window_byte"]
            or mapping["discarded_source_packet_indices"] != [r["source_packet_index"] for r in records if r["window_byte"] is None]):
        raise ValueError("saved window does not exactly reconstruct from the source mapping")
    return True


def choose_packet(packets, pts):
    """Return the demuxed/coded packet index, not the rank of its PTS.

    Leading absent DTS values occur normally with B pictures. Once DTS is
    available, require strictly increasing decode timestamps with no holes.
    Every picture must have a unique integer PTS; do not guess missing timing.
    """
    timestamps, previous_dts = set(), None
    for packet in packets:
        timestamp = packet.get("pts")
        if type(timestamp) is not int:
            raise ValueError("every source packet must have an integer PTS")
        if timestamp in timestamps:
            raise ValueError("source packet PTS values must be unique")
        timestamps.add(timestamp)
        dts = packet.get("dts")
        if dts is None:
            if previous_dts is not None:
                raise ValueError("missing DTS after decode timestamps began")
        elif type(dts) is not int or (previous_dts is not None and dts <= previous_dts):
            raise ValueError("known DTS values must be strictly increasing integers")
        else:
            previous_dts = dts
    if packets and previous_dts is None:
        raise ValueError("at least one decode timestamp is required")
    matches = [index for index, packet in enumerate(packets) if packet["pts"] == pts]
    if len(matches) != 1:
        raise ValueError("expected exactly one packet at the requested PTS")
    return matches[0]


def rpu_presentation_order(packets, rpu_indices, el_indices, reordered):
    """Map RPU export order back to coded source-packet indices.

    dovi_tool 2.3.4 general_read_write.rs flush_writer sorts exported RPUs by
    presentation order. Its missing-RPU indexing is not safe to infer for a
    reordered stream, so require one EL and RPU per coded picture in that case.
    """
    if reordered and (rpu_indices != list(range(len(packets)))
                      or el_indices != list(range(len(packets)))):
        raise ValueError("reordered sources require exactly one EL and RPU per coded picture")
    return sorted(range(len(rpu_indices)), key=lambda i: packets[rpu_indices[i]]["pts"])


def decoded_picture_index(decoded, packet_position):
    """Identify the displayed picture by its packet byte position, not ordinal."""
    matches = [i for i, frame in enumerate(decoded) if str(frame.get("pkt_pos")) == str(packet_position)]
    if len(matches) != 1:
        raise ValueError("source packet must produce exactly one decoded picture with a packet position")
    return matches[0]


def verify_picture_geometry(expected, decoded):
    """Do not silently label a target using stale initial-stream SPS geometry."""
    for field in ("width", "height", "pix_fmt", "chroma_location"):
        if expected.get(field) is None or decoded.get(field) != expected[field]:
            raise ValueError(f"decoded target {field} does not match declared stream geometry")
    return True


def copy_window(source, destination, start, end):
    """Copy an exact byte interval without retaining a compressed GOP in RAM."""
    if not 0 <= start < end <= Path(source).stat().st_size:
        raise ValueError("invalid decode-window byte interval")
    with Path(source).open("rb") as src, Path(destination).open("xb") as dst:
        src.seek(start)
        remaining = end - start
        while remaining:
            chunk = src.read(min(1024 * 1024, remaining))
            if not chunk:
                raise ValueError("truncated decode-window source")
            dst.write(chunk)
            remaining -= len(chunk)


def split_planes(path, width, height, directory, prefix):
    counts = [width * height, width * height // 4, width * height // 4]
    raw = path.read_bytes()
    if width % 2 or height % 2 or len(raw) != sum(counts) * 2:
        raise ValueError(f"{prefix}: unexpected decoded frame dimensions/size")
    planes, offset = {}, 0
    for channel, count in zip(("Y", "Cb", "Cr"), counts):
        data = raw[offset:offset + count * 2]
        samples = array("H")
        samples.frombytes(data)
        if sys.byteorder != "little":
            samples.byteswap()
        if max(samples) > 1023:
            raise ValueError("decoded samples are not right-aligned 10-bit codes")
        name = f"{prefix}_{channel}.u16le"
        with (directory / name).open("xb") as handle:
            handle.write(data)
        planes[channel] = {"file": name, "sha256": hashlib.sha256(data).hexdigest(),
                           "samples": count, "minimum": min(samples), "maximum": max(samples)}
        offset += count * 2
    return planes


class Commands:
    def __init__(self, directory):
        self.directory = directory
        self.commands = []

    def run(self, name, command):
        print(f"{name} ...", flush=True)
        stdout, stderr = self.directory / f"{name}.stdout", self.directory / f"{name}.stderr"
        self.commands.append({"name": name, "argv": [str(v) for v in command]})
        with stdout.open("xb") as out, stderr.open("xb") as err:
            process = subprocess.run(command, stdout=out, stderr=err)
        if process.returncode:
            raise ValueError(f"{name} failed ({process.returncode}); see {stderr}")
        return stdout.read_bytes()

    def probe(self, name, arguments, source):
        return json.loads(self.run(name, ["ffprobe", "-v", "error", *arguments,
                                          "-of", "json", str(source)]))


def extract(source, output, pts, dovi_tool, expected_sha256=None, max_window_frames=1024):
    if type(max_window_frames) is not int or max_window_frames < 1:
        raise ValueError("max_window_frames must be a positive integer")
    source, output, dovi_tool = Path(source).resolve(), Path(output).resolve(), Path(dovi_tool).resolve()
    source_hash = digest(source)
    if expected_sha256 and source_hash != expected_sha256:
        raise ValueError("source checksum differs from the requested reference")
    output.mkdir(exist_ok=False)
    commands = Commands(output)
    tool_versions = {"ffmpeg": commands.run("ffmpeg-version", ["ffmpeg", "-version"]).decode(),
                     "dovi_tool": commands.run("dovi-version", [str(dovi_tool), "--version"]).decode()}
    source_info = commands.probe("source-streams", ["-show_streams", "-show_data"], source)
    video = [s for s in source_info["streams"] if s["codec_type"] == "video"]
    if len(video) != 1 or video[0]["codec_name"] != "hevc":
        raise ValueError("only single-track HEVC is currently supported")
    stream = video[0]
    config = next((s for s in stream.get("side_data_list", [])
                   if s["side_data_type"] == "DOVI configuration record"), {})
    if config.get("dv_profile") != 7 or not all(config.get(k) == 1 for k in
                                               ("bl_present_flag", "el_present_flag", "rpu_present_flag")):
        raise ValueError("input must declare Profile 7 with both layers and RPU")
    extradata = unhex_dump(stream["extradata"])
    if len(extradata) < 23 or extradata[0] != 1:
        raise ValueError("expected HEVC configuration record")
    length_size = (extradata[21] & 3) + 1
    packets = commands.probe("source-packets", ["-select_streams", "v:0", "-show_packets",
        "-show_entries", "packet=pts,dts,pos,size,flags"], source)["packets"]
    index = choose_packet(packets, pts)
    reordered = bool(stream.get("has_b_frames")) or any(a["pts"] > b["pts"] for a, b in zip(packets, packets[1:]))
    keyframe = max(i for i in range(index + 1) if "K" in packets[i]["flags"])
    numerator, denominator = map(int, stream["time_base"].split("/"))
    start = packets[keyframe]["pts"] * numerator / denominator
    count = index - keyframe + 2
    if count > max_window_frames + 1:
        raise ValueError("container keyframe interval exceeds --max-window-frames; use a shorter self-contained source clip")
    packet_data = commands.probe("target-packet-data", ["-select_streams", "v:0", "-read_intervals",
        f"{start:.9f}%+#{count}", "-show_packets", "-show_data",
        "-show_entries", "packet=pts,dts,pos,size,data"], source)["packets"]
    targets = [p for p in packet_data if p.get("pts") == pts]
    if len(targets) != 1:
        raise ValueError("seek must recover exactly one packet at the target PTS; no ordinal fallback")
    target = targets[0]
    if target["pos"] != packets[index]["pos"]:
        raise ValueError("packet lookup changed source position")
    payload = unhex_dump(target["data"])
    if len(payload) != int(target["size"]):
        raise ValueError("packet dump byte count mismatch")
    # Hex dump text is many times larger than the compressed packet, and this
    # probe includes preceding packets from the seek point. Release it before
    # launching any decoder subprocess inside the shared memory cap.
    del packet_data, target, targets
    with (output / "source-packet.bin").open("xb") as handle:
        handle.write(payload)
    units = length_prefixed_nals(payload, length_size)
    source_bl = [unit for unit in units if nal_type(unit) < 32]
    source_el = [unit[2:] for unit in units if nal_type(unit) == 63 and nal_type(unit[2:]) < 32]
    source_rpu = [unit for unit in units if nal_type(unit) == 62]
    if not source_bl or not source_el or len(source_rpu) != 1:
        raise ValueError("target packet must contain BL, wrapped EL and exactly one RPU")
    packet_count, packet_el, packet_rpu, _ = layer_associations(units)
    if packet_count != 1 or packet_el != [0] or packet_rpu != [0]:
        raise ValueError("target packet must contain exactly one paired BL/EL/RPU picture")
    with (output / "frame.rpu.nal").open("xb") as handle:
        handle.write(source_rpu[0])
    with (output / "frame.rpu.bin").open("xb") as handle:
        # dovi_tool's RPU.bin representation omits the two-byte HEVC NAL header.
        handle.write(b"\x00\x00\x00\x01" + source_rpu[0][2:])

    hevc = output / "source.hevc"
    commands.run("annexb-remux", ["ffmpeg", "-nostdin", "-v", "error", "-n", "-i", str(source),
        "-map", "0:v:0", "-c:v", "copy", "-bsf:v", "hevc_mp4toannexb", "-f", "hevc", str(hevc)])
    bl_path, el_path, rpu_path = output / "BL.hevc", output / "EL.hevc", output / "RPU.bin"
    commands.run("demux", [str(dovi_tool), "demux", str(hevc), "--bl-out", str(bl_path), "--el-out", str(el_path)])
    commands.run("extract-rpu", [str(dovi_tool), "extract-rpu", str(hevc), "-o", str(rpu_path)])
    bl_count, el_indices, rpu_indices, packet_rpu_hashes = layer_associations(annexb_file(hevc), hash_rpus=True)
    if bl_count != len(packets) or index not in el_indices or index not in rpu_indices:
        raise ValueError("source stream association does not contain the selected BL/EL/RPU")
    el_index, coded_rpu_index = el_indices.index(index), rpu_indices.index(index)
    rpu_order = rpu_presentation_order(packets, rpu_indices, el_indices, reordered)
    rpu_index = rpu_order.index(coded_rpu_index)
    rpu_hashes = [hashlib.sha256(unit).digest() for unit in annexb_file(rpu_path)]
    if (rpu_hashes != [packet_rpu_hashes[i] for i in rpu_order]
            or rpu_hashes[rpu_index] != hashlib.sha256(source_rpu[0][2:]).digest()):
        raise ValueError("extracted RPUs do not match source associations and exact target packet")
    rpu_raw = commands.run("target-rpu-json", [str(dovi_tool), "info", "-i", str(output / "frame.rpu.bin"), "-f", "0"])
    # Some tool versions print a progress line before the serialized object.
    rpu_text = rpu_raw.decode()
    rpu_json = json.loads(rpu_text[rpu_text.index("{"):])
    if rpu_json.get("header", {}).get("use_prev_vdr_rpu_flag") is not False:
        raise ValueError("target RPU must be self-contained; previous-RPU reuse is unsupported")
    save_json(output / "rpu.json", rpu_json)
    global_raw = commands.run("global-rpu-json", [str(dovi_tool), "info", "-i", str(rpu_path), "-f", str(rpu_index)]).decode()
    if json.loads(global_raw[global_raw.index("{"):]) != rpu_json:
        raise ValueError("direct-packet and global-index metadata differ")

    layers = {}
    for label, path, expected in (("bl", bl_path, source_bl), ("el", el_path, source_el)):
        decode_index = index if label == "bl" else el_index
        expected_count = len(packets) if label == "bl" else len(el_indices)
        vcl, frame_count = frame_vcl(annexb_file(path), decode_index)
        picture_types = picture_nal_types(annexb_file(path))
        if len(picture_types) != frame_count:
            raise ValueError(f"{label}: inconsistent coded picture classification")
        plan = random_access_plan(picture_types, decode_index, max_window_frames)
        start_index = plan["start"]
        if frame_count != expected_count or vcl != expected:
            raise ValueError(f"{label}: demuxed frame VCL does not match the exact source packet")
        info = commands.probe(f"{label}-stream", ["-show_streams"], path)["streams"][0]
        if info["pix_fmt"] != "yuv420p10le":
            raise ValueError(f"{label}: unsupported decoding format")
        # EL may advertise decoder reordering even when the container does not.
        # Resolve the presentation index from the decoder's source packet offset,
        # not from a presumed equality between coded and displayed frame numbers.
        raw_packets = commands.probe(f"{label}-packets", ["-show_packets", "-show_entries",
            "packet=pos,size"], path)["packets"]
        if len(raw_packets) != frame_count:
            raise ValueError(f"{label}: demuxed packet count differs from coded picture count")
        raw_packet = raw_packets[decode_index]
        with path.open("rb") as handle:
            handle.seek(int(raw_packet["pos"]))
            encoded_picture = handle.read(int(raw_packet["size"]))
        if not packet_vcl_matches([n for n in annexb_nals(encoded_picture) if nal_type(n) < 32], expected):
            raise ValueError(f"{label}: decoder packet does not match source VCL")
        del encoded_picture
        # Access points may differ between the layers. Filter only complete
        # initial-CRA RASL pictures, with an explicit source->window byte map;
        # a target that needs those leading pictures chooses an earlier CRA.
        start_packet = raw_packets[start_index]
        start_offset = int(start_packet["pos"])
        window = output / f"{label}-decode-window.hevc"
        window_mapping = write_picture_window(path, window, raw_packets, picture_types, plan,
                                               range(len(packets)) if label == "bl" else el_indices)
        # Reparse the actual saved target packet. The rewritten offset must
        # identify exactly the original target VCLs, not merely a shifted index.
        with window.open("rb") as handle:
            handle.seek(window_mapping["target_window_byte"])
            written_target = handle.read(int(raw_packet["size"]))
        if not packet_vcl_matches([n for n in annexb_nals(written_target) if nal_type(n) < 32], expected):
            raise ValueError(f"{label}: rewritten window changed the target VCL")
        del written_target
        decoded = commands.probe(f"{label}-frames", ["-threads", "4", "-err_detect", "explode",
            "-show_frames", "-show_entries",
            "frame=pkt_pos,pkt_size,pict_type,width,height,pix_fmt,chroma_location"], window)["frames"]
        if (output / f"{label}-frames.stderr").read_text().strip():
            raise ValueError(f"{label}: decoder reported an error in the target's random-access window")
        window_target_pos = str(window_mapping["target_window_byte"])
        presentation_index = decoded_picture_index(decoded, window_target_pos)
        verify_picture_geometry(info, decoded[presentation_index])
        raw = output / f"{label}.yuv"
        commands.run(f"decode-{label}", ["ffmpeg", "-nostdin", "-v", "info", "-n", "-xerror",
            "-threads", "4", "-err_detect", "explode",
            "-i", str(window), "-map", "0:v:0", "-vf", f"select=eq(n\\,{presentation_index}),showinfo",
            "-filter_threads", "1", "-frames:v", "1", "-fps_mode", "passthrough",
            "-c:v", "rawvideo", "-threads:v", "1", "-pix_fmt", "+yuv420p10le", "-f", "rawvideo", str(raw)])
        layers[label] = {"width": info["width"], "height": info["height"],
                         "chroma_location": info.get("chroma_location", "unspecified"),
                         "decode_index_zero_based": decode_index,
                         "decode_index_scope": "coded picture order in this demuxed layer; not display order",
                         "presentation_index_zero_based": presentation_index,
                         "presentation_index_scope": "local random-access decode window",
                         "window_start_source_index": start_index if label == "bl" else el_indices[start_index],
                         "window_coded_picture_count": decode_index - start_index + 1,
                         "window_start_byte": start_offset,
                         "window_target_byte": window_mapping["target_window_byte"],
                         "window_mapping": window_mapping,
                         "window_sha256": digest(window),
                         "decoder_packet": raw_packet,
                         "decoded_frame": decoded[presentation_index],
                         "frame_count": frame_count, "vcl_nal_count": len(vcl),
                         "source_packet_vcl_identical": True, "stream": info,
                         "raw_sha256": digest(raw), "planes": split_planes(
                             raw, info["width"], info["height"], output, label)}
    report = {"schema": "yblod.extracted-frame.v1", "status": "complete",
              "source": str(source), "source_sha256": source_hash,
              "source_packet_index_zero_based": index, "source_packet": packets[index],
              "source_packet_index_scope": "container demux/coded packet order; not a visible frame counter",
              "source_presentation_rank_zero_based": sum(packet["pts"] < pts for packet in packets),
              "source_presentation_rank_scope": "unique source packet PTS order; not verified against an on-screen counter",
              "source_has_reordered_pictures": reordered, "maximum_window_coded_pictures": max_window_frames,
              "pts": pts, "time_base": [numerator, denominator], "source_packet_sha256": hashlib.sha256(payload).hexdigest(),
              "rpu_count": len(rpu_hashes), "rpu_matches_source_packet_and_global_index": True,
              "rpu_index_zero_based": rpu_index,
              "rpu_index_scope": "dovi_tool RPU.bin presentation order, cross-checked against source PTS order",
              "rpu_coded_index_zero_based": coded_rpu_index,
              "missing_el_source_indices": sorted(set(range(bl_count)) - set(el_indices)),
              "missing_rpu_source_indices": sorted(set(range(bl_count)) - set(rpu_indices)),
              "rpu_sha256": digest(output / "frame.rpu.bin"),
              "rpu_json_sha256": digest(output / "rpu.json"),
              "layers": layers, "tool_versions": tool_versions, "dovi_tool_sha256": digest(dovi_tool),
              "extractor_sha256": digest(__file__), "commands": commands.commands,
              "preparation": "Native decoded layers only: no resampling, colour conversion or range expansion.",
              "visible_counter_verified": False}
    save_json(output / "extraction.json", report)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path, help="new extraction directory")
    parser.add_argument("--pts", type=int, required=True, help="exact source-stream PTS, not seconds")
    parser.add_argument("--dovi-tool", type=Path, required=True)
    parser.add_argument("--expected-sha256")
    parser.add_argument("--max-window-frames", type=int, default=1024,
                        help="maximum coded pictures per decode window (default: 1024); never an inferred display index")
    args = parser.parse_args()
    try:
        report = extract(args.source, args.output, args.pts, args.dovi_tool, args.expected_sha256, args.max_window_frames)
    except (OSError, ValueError, KeyError, StopIteration) as error:
        parser.exit(1, f"extraction: {error}\n")
    print(f"Extracted coded source packet {report['source_packet_index_zero_based']} at PTS {report['pts']}; not a visible frame number")
