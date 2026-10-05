#!/usr/bin/env python3
"""Extract one non-reordered P7 frame's native layers and matching RPU.

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


def layer_associations(units):
    """Associate wrapped EL/RPU units with the preceding BL first slice.

    Restricted to non-reordered streams whose EL and RPU follow their BL, as
    verified again against the exact container packet for the requested frame.
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
            rpus.append(unit[2:])
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


def choose_packet(packets, pts):
    if any(p.get("pts") != p.get("dts") or p.get("pts") is None for p in packets):
        raise ValueError("reordered/missing timestamps are not supported by this extractor")
    if any(a["pts"] >= b["pts"] for a, b in zip(packets, packets[1:])):
        raise ValueError("packet timestamps must be strictly increasing")
    matches = [index for index, packet in enumerate(packets) if packet["pts"] == pts]
    if len(matches) != 1:
        raise ValueError("expected exactly one packet at the requested PTS")
    return matches[0]


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


def extract(source, output, pts, dovi_tool, expected_sha256=None):
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
    if len(video) != 1 or video[0]["codec_name"] != "hevc" or video[0].get("has_b_frames") != 0:
        raise ValueError("only single-track, non-reordered HEVC is currently supported")
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
    keyframe = max(i for i in range(index + 1) if "K" in packets[i]["flags"])
    numerator, denominator = map(int, stream["time_base"].split("/"))
    start = packets[keyframe]["pts"] * numerator / denominator
    count = index - keyframe + 2
    packet_data = commands.probe("target-packet-data", ["-select_streams", "v:0", "-read_intervals",
        f"{start:.9f}%+#{count}", "-show_packets", "-show_data",
        "-show_entries", "packet=pts,dts,pos,size,data"], source)["packets"]
    target = next(p for p in packet_data if p["pts"] == pts)
    if target["pos"] != packets[index]["pos"]:
        raise ValueError("packet lookup changed source position")
    payload = unhex_dump(target["data"])
    if len(payload) != int(target["size"]):
        raise ValueError("packet dump byte count mismatch")
    with (output / "source-packet.bin").open("xb") as handle:
        handle.write(payload)
    units = length_prefixed_nals(payload, length_size)
    source_bl = [unit for unit in units if nal_type(unit) < 32]
    source_el = [unit[2:] for unit in units if nal_type(unit) == 63 and nal_type(unit[2:]) < 32]
    source_rpu = [unit for unit in units if nal_type(unit) == 62]
    if not source_bl or not source_el or len(source_rpu) != 1:
        raise ValueError("target packet must contain BL, wrapped EL and exactly one RPU")
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
    bl_count, el_indices, rpu_indices, packet_rpus = layer_associations(annexb_file(hevc))
    if bl_count != len(packets) or index not in el_indices or index not in rpu_indices:
        raise ValueError("source stream association does not contain the selected BL/EL/RPU")
    el_index, rpu_index = el_indices.index(index), rpu_indices.index(index)
    rpus = annexb_nals(rpu_path.read_bytes())
    if rpus != packet_rpus or rpus[rpu_index] != source_rpu[0][2:]:
        raise ValueError("extracted RPUs do not match source associations and exact target packet")
    rpu_raw = commands.run("target-rpu-json", [str(dovi_tool), "info", "-i", str(output / "frame.rpu.bin"), "-f", "0"])
    # Some tool versions print a progress line before the serialized object.
    rpu_text = rpu_raw.decode()
    rpu_json = json.loads(rpu_text[rpu_text.index("{"):])
    save_json(output / "rpu.json", rpu_json)
    global_raw = commands.run("global-rpu-json", [str(dovi_tool), "info", "-i", str(rpu_path), "-f", str(rpu_index)]).decode()
    if json.loads(global_raw[global_raw.index("{"):]) != rpu_json:
        raise ValueError("direct-packet and global-index metadata differ")

    layers = {}
    for label, path, expected in (("bl", bl_path, source_bl), ("el", el_path, source_el)):
        decode_index = index if label == "bl" else el_index
        expected_count = len(packets) if label == "bl" else len(el_indices)
        vcl, frame_count = frame_vcl(annexb_file(path), decode_index)
        # EL commonly uses open GOPs with multi-slice RASL pictures. Start at a
        # closed IDR to avoid dropping their first slices after a CRA seek.
        start_index = last_random_access(annexb_file(path), decode_index,
                                         (19, 20) if label == "el" else (19, 20, 21))
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
        # Decode from a local random-access picture, not through unrelated errors
        # earlier in the movie. Require a complete parameter set and an IRAP in
        # BOTH layers. Their access points need not coincide with each other or
        # with container keyframe flags; select independently by each bitstream.
        start_packet = raw_packets[start_index]
        start_offset = int(start_packet["pos"])
        end_offset = int(raw_packet["pos"]) + int(raw_packet["size"])
        with path.open("rb") as handle:
            handle.seek(start_offset)
            start_bytes = handle.read(int(start_packet["size"]))
            handle.seek(start_offset)
            window_bytes = handle.read(end_offset - start_offset)
        start_types = {nal_type(n) for n in annexb_nals(start_bytes)}
        if not {32, 33, 34}.issubset(start_types) or not start_types.intersection({19, 20, 21}):
            raise ValueError(f"{label}: random-access picture is not self-contained")
        window = output / f"{label}-decode-window.hevc"
        with window.open("xb") as handle:
            handle.write(window_bytes)
        decoded = commands.probe(f"{label}-frames", ["-threads", "4", "-err_detect", "explode",
            "-show_frames", "-show_entries",
            "frame=pkt_pos,pkt_size,pict_type,width,height,pix_fmt,chroma_location"], window)["frames"]
        if (output / f"{label}-frames.stderr").read_text().strip():
            raise ValueError(f"{label}: decoder reported an error in the target's random-access window")
        window_target_pos = str(int(raw_packet["pos"]) - start_offset)
        matching = [i for i, frame in enumerate(decoded) if frame.get("pkt_pos") == window_target_pos]
        if len(matching) != 1:
            raise ValueError(f"{label}: source packet must produce exactly one decoded picture")
        presentation_index = matching[0]
        raw = output / f"{label}.yuv"
        commands.run(f"decode-{label}", ["ffmpeg", "-nostdin", "-v", "info", "-n", "-xerror",
            "-threads", "4", "-err_detect", "explode",
            "-i", str(window), "-map", "0:v:0", "-vf", f"select=eq(n\\,{presentation_index}),showinfo",
            "-filter_threads", "1", "-frames:v", "1", "-fps_mode", "passthrough",
            "-c:v", "rawvideo", "-threads:v", "1", "-pix_fmt", "+yuv420p10le", "-f", "rawvideo", str(raw)])
        layers[label] = {"width": info["width"], "height": info["height"],
                         "chroma_location": info.get("chroma_location", "unspecified"),
                         "decode_index_zero_based": decode_index,
                         "presentation_index_zero_based": presentation_index,
                         "presentation_index_scope": "local random-access decode window",
                         "window_start_source_index": start_index if label == "bl" else el_indices[start_index],
                         "window_start_byte": start_offset,
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
              "pts": pts, "time_base": [numerator, denominator], "source_packet_sha256": hashlib.sha256(payload).hexdigest(),
              "rpu_count": len(rpus), "rpu_matches_source_packet_and_global_index": True,
              "rpu_index_zero_based": rpu_index,
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
    args = parser.parse_args()
    try:
        report = extract(args.source, args.output, args.pts, args.dovi_tool, args.expected_sha256)
    except (OSError, ValueError, KeyError, StopIteration) as error:
        parser.exit(1, f"extraction: {error}\n")
    print(f"Extracted source packet/frame index {report['source_packet_index_zero_based']} at PTS {report['pts']}")
