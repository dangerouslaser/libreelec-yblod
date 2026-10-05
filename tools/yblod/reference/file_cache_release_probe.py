"""Opt-in CPU-only 8 MiB cache observation. No GPU or global cache operation."""
import argparse
import hashlib
import json
from pathlib import Path
import resource
import sys
import time

import file_cache_release as release

FILE_BYTES=8*1024*1024
CHUNK_BYTES=65536


def file_hash(path):
    """Hash only probe-sized inputs, bounded even if a writer keeps appending."""
    digest=hashlib.sha256();remaining=FILE_BYTES
    with Path(path).open("rb") as handle:
        while True:
            data=handle.read(min(CHUNK_BYTES,remaining+1))
            if not data:break
            if len(data)>remaining:raise ValueError("file exceeds bounded probe hash size")
            digest.update(data);remaining-=len(data)
    return digest.hexdigest()


def memory_snapshot():
    """Optional unified-cgroup observations, not process-only memory."""
    try:
        line=next(v for v in Path("/proc/self/cgroup").read_text().splitlines() if v.startswith("0::"))
        root=Path("/sys/fs/cgroup").resolve();scope=(root/line[3:].lstrip("/")).resolve()
        if scope!=root and root not in scope.parents:raise ValueError("invalid cgroup scope")
        result={"available":True,"scope":str(scope)}
        for name in ("memory.current","memory.peak","memory.swap.current","memory.swap.peak","memory.max","memory.swap.max"):
            path=scope/name
            if path.exists():
                value=path.read_text().strip();result[name]=value if value=="max" else int(value)
        for name in ("memory.stat","memory.events"):
            result[name]={key:int(value) for key,value in (row.split() for row in (scope/name).read_text().splitlines())}
        return result
    except (OSError,ValueError,StopIteration) as error:return {"available":False,"reason":str(error)}


def run(destination):
    root=Path(destination).resolve();root.mkdir(exist_ok=False)
    started=time.monotonic();sources=(Path(__file__).resolve(),Path(release.__file__).resolve())
    pins={p.name:file_hash(p) for p in sources}
    report={"schema":"yblod.file-cache-release-probe.v1","status":"failed","source_sha256":pins,
            "file":"synthetic-8m.bin","bytes":FILE_BYTES,"snapshots":[],"gpu_jobs":0,
            "interpretation":"CPU-only per-file advice observations. No eviction guarantee, deletion, global cache action or playback measurement."}
    def snapshot(stage):report["snapshots"].append({"stage":stage,"memory":memory_snapshot()})
    try:
        snapshot("before_write")
        path=root/report["file"];chunk=bytes(range(256))*256;digest=hashlib.sha256()
        with path.open("xb") as handle:
            for _ in range(FILE_BYTES//CHUNK_BYTES):handle.write(chunk);digest.update(chunk)
        report["expected_sha256"]=digest.hexdigest();snapshot("after_write")
        before=file_hash(path)
        if path.stat().st_size!=FILE_BYTES or before!=digest.hexdigest():raise ValueError("generated file verification failed")
        report["before_advice_sha256"]=before;snapshot("after_hash")
        report["advice"]=release.release_verified_file(path,before,FILE_BYTES)
        snapshot("immediately_after_advice_before_rehash")
        after=file_hash(path);report["after_advice_sha256"]=after
        snapshot("after_rehash")
        if path.stat().st_size!=FILE_BYTES or after!=before:raise ValueError("file changed after advice")
        if any(file_hash(p)!=pins[p.name] for p in sources):raise ValueError("probe/helper source changed")
        report.update(status="complete",file_preserved_hash_exact=True)
    except Exception as error:report["error"]={"type":type(error).__name__,"message":str(error)}
    report["resources"]={"elapsed_seconds":time.monotonic()-started,"process_peak_rss_native":resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                         "rss_unit":"bytes" if sys.platform=="darwin" else "KiB"}
    with (root/"file-cache-probe-report.json").open("x") as handle:json.dump(report,handle,indent=2);handle.write("\n")
    return report


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument("new_directory")
    result=run(parser.parse_args().new_directory)
    print(json.dumps({"status":result["status"],"bytes":result["bytes"],"gpu_jobs":0}))
    raise SystemExit(result["status"]!="complete")
