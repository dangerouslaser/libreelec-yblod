"""Diagnostic-only, exact single-EOF-zero fixture derivation; not normalization."""
import hashlib
import os
from pathlib import Path
import re
import stat

LIMIT = 4 * 1024 * 1024


def verify_aud_boundary(window, *, window_sha256, legacy_position, legacy_size):
    """Predict this one FFmpeg6→9 boundary relation from pinned bytes, not output.

    The legacy position owns a three-byte suffix of the target AUD's four-byte
    delimiter. The derived window already removed precisely one EOF zero.
    """
    source = _read(window, window_sha256)
    if (type(legacy_position) is not int or type(legacy_size) is not int
            or legacy_position < 1 or legacy_size < 1
            or legacy_position + legacy_size != len(source) + 1):
        raise ValueError("unsupported legacy packet extent")
    start = legacy_position - 1
    if source[start:start + 4] != b"\x00\x00\x00\x01":
        raise ValueError("no exact four-byte target delimiter")
    if start and source[start - 1] == 0:
        raise ValueError("ambiguous longer delimiter run")
    header = source[start + 4:start + 6]
    if header != b"\x46\x01":
        raise ValueError("target is not layer-zero temporal-zero HEVC AUD")
    return {"canonical_aud_position": start, "canonical_packet_size": len(source) - start,
            "legacy_position": legacy_position, "legacy_size": legacy_size,
            "leading_startcode_zero_reassigned_bytes": 1,
            "removed_verified_eof_zero_bytes": 1,
            "identity_predicted_from_source_bytes": True}


def _read(path, expected):
    if not isinstance(expected, str) or re.fullmatch(r"[0-9a-f]{64}", expected) is None:
        raise ValueError("invalid expected hash")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or not 0 < before.st_size <= LIMIT:
            raise ValueError("unsupported input extent")
        pieces, remaining = [], before.st_size
        while remaining:
            piece = os.read(fd, min(65536, remaining))
            if not piece:
                raise ValueError("truncated input")
            pieces.append(piece)
            remaining -= len(piece)
        if os.read(fd, 1):
            raise ValueError("input grew")
        data = b"".join(pieces)
        after = os.fstat(fd)
        fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
        if any(getattr(before, field) != getattr(after, field) for field in fields):
            raise ValueError("input changed")
        if hashlib.sha256(data).hexdigest() != expected:
            raise ValueError("input hash mismatch")
        return data
    finally:
        os.close(fd)


def derive(window, canonical_nal, output, *, window_sha256, canonical_nal_sha256,
           packet_position, packet_size):
    """Verify one specific transport discrepancy and exclusively write a fixture.

    Caller supplies pinned inputs and target packet extent; no frame searching,
    decoding, instruction parsing, RPU rewriting, or generic zero stripping.
    Returned hashes describe private fixtures and are not public checkpoints.
    """
    if (type(packet_position) is not int or type(packet_size) is not int
            or packet_position < 0 or packet_size <= 0):
        raise ValueError("invalid packet extent")
    source = _read(window, window_sha256)
    canonical = _read(canonical_nal, canonical_nal_sha256)
    if (len(canonical) < 3 or canonical[-1] != 0x80
            or canonical[0] & 0x80 or (canonical[0] >> 1) & 63 != 62
            or canonical[0] & 1 or canonical[1] >> 3 or canonical[1] & 7 != 1):
        raise ValueError("unsupported canonical RPU NAL")
    # Include every zero in the delimiter run, rather than arbitrarily assigning
    # the fourth start-code zero to the preceding NAL. The final NAL has no next
    # delimiter: its precise remaining extent must be canonical+exactly one zero.
    last = None
    for delimiter in re.finditer(rb"\x00{2,}\x01", source):
        last = delimiter
    if last is None:
        raise ValueError("no Annex-B delimiter")
    if source[last.end():] != canonical + b"\x00":
        raise ValueError("final NAL is not exact canonical plus one EOF zero")
    if packet_position + packet_size != len(source) or last.start() < packet_position:
        raise ValueError("target packet does not contain the final NAL at EOF")
    destination = Path(output)
    parent_state = destination.parent.stat()
    if (not stat.S_ISDIR(parent_state.st_mode) or parent_state.st_mode & 0o077
            or parent_state.st_uid != os.geteuid()):
        raise ValueError("output parent is not private and owned")
    result = source[:-1]
    fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    created = os.fstat(fd)
    success = False
    try:
        view = memoryview(result)
        while view:
            written = os.write(fd, view[:65536])
            if written <= 0:
                raise OSError("short fixture write")
            view = view[written:]
        os.fsync(fd)
        # Recheck independently pinned originals after writing. No live input
        # descriptor or externally supplied metadata drives the written bytes.
        _read(window, window_sha256)
        _read(canonical_nal, canonical_nal_sha256)
        derived_hash = hashlib.sha256(result).hexdigest()
        _read(destination, derived_hash)
        success = True
    finally:
        os.close(fd)
        if not success:
            current = destination.lstat()
            if (current.st_dev, current.st_ino) == (created.st_dev, created.st_ino):
                destination.unlink()
    return {"schema": "yblod.decoder-window-fixture.v1", "status": "complete",
            "original_window_sha256": window_sha256,
            "canonical_nal_sha256": canonical_nal_sha256,
            "derived_window_sha256": derived_hash,
            "original_bytes": len(source), "derived_bytes": len(result),
            "removed_verified_eof_zero_bytes": 1,
            "packet_position": packet_position, "original_packet_size": packet_size,
            "derived_packet_size": packet_size - 1,
            "originals_retained": True, "canonical_nal_unchanged": True}
