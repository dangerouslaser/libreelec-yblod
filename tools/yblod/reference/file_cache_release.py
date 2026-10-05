"""Opt-in Linux per-file cache advice after verified evidence is durable.

Not integrated into measured runners. No unlink/truncate/write/global cache
operation. Caller must finish/close all writers and readers and retain stable
ownership throughout this call. Advice can affect other readers of this file;
it does not prove eviction or bound memory. fsync does not persist a new parent
directory entry. See https://man7.org/linux/man-pages/man2/posix_fadvise.2.html
"""
import hashlib
import os
from pathlib import Path
import re
import stat


def _identity(value):
    return (value.st_dev,value.st_ino,value.st_size,value.st_mtime_ns,value.st_ctime_ns)


def release_verified_file(path,expected_sha256,expected_bytes):
    """Verify through a read-only fd, fsync, then advise DONTNEED for this file.

    Raise on unsupported platforms, identity/hash changes or syscall failures;
    no silent fallback. Report advice submission, NEVER claimed bytes freed.
    The bounded verification itself may fault pages into cache. Call before
    admitting the next output, not after accumulating an entire large cohort.
    """
    if type(expected_bytes) is not int or expected_bytes<0:
        raise ValueError("nonnegative integer expected byte count required")
    if type(expected_sha256) is not str or re.fullmatch("[0-9a-f]{64}",expected_sha256) is None:
        raise ValueError("lowercase SHA256 required")
    if not callable(getattr(os,"posix_fadvise",None)) or not hasattr(os,"POSIX_FADV_DONTNEED") or not hasattr(os,"O_NOFOLLOW"):
        raise NotImplementedError("explicit Linux no-follow per-file cache advice required")
    path=Path(path)
    before=path.lstat()
    if not stat.S_ISREG(before.st_mode) or before.st_size!=expected_bytes:
        raise ValueError("regular nonsymlink file with exact byte count required")
    descriptor=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    try:
        opened=os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode) or _identity(opened)!=_identity(before):
            raise ValueError("file changed before verification")
        digest=hashlib.sha256()
        remaining=expected_bytes
        while True:
            data=os.read(descriptor,min(65536,remaining+1))
            if not data:break
            if len(data)>remaining:raise ValueError("file grew beyond declared byte count")
            digest.update(data)
            remaining-=len(data)
        if remaining:raise ValueError("file truncated during verification")
        if digest.hexdigest()!=expected_sha256 or _identity(os.fstat(descriptor))!=_identity(opened) or _identity(path.lstat())!=_identity(opened):
            raise ValueError("file identity/content changed or hash mismatch")
        os.fsync(descriptor)
        if _identity(os.fstat(descriptor))!=_identity(opened) or _identity(path.lstat())!=_identity(opened):
            raise ValueError("file changed during sync")
        os.posix_fadvise(descriptor,0,0,os.POSIX_FADV_DONTNEED)
        return {"verified_sha256":expected_sha256,"bytes":expected_bytes,
                "file_data_fsync_completed":True,"dontneed_advice_submitted":True,
                "range_offset":0,"range_length":0,"range_length_zero_means_to_eof":True,
                "eviction_verified":False,"file_deleted":False}
    finally:os.close(descriptor)
