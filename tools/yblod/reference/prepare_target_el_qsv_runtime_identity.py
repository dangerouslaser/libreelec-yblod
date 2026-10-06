"""Private code-only target closure producer; no driver/core overlays or GPU work."""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
from observe_live_el_qsv_probe import code_fingerprint, resources


def needed_names(data):
    """Both GNU and target elfutils readelf; unparsed NEEDED is an error."""
    names=[]
    for line in data.splitlines():
        if not re.search(r'\bNEEDED\b',line):
            continue
        match=re.search(r'\bNEEDED\)?\s+Shared library:\s*\[([^\]]+)\]',line)
        if match is None:
            raise ValueError('Unrecognized target dependency listing')
        names.append(match.group(1))
    return names


def closure(runtime, driver, loader):
    if shutil.which('readelf') is None:
        raise ValueError('Target readelf required before closure preparation')
    runtime = Path(runtime).resolve(strict=True)
    system = Path('/usr/lib').resolve(strict=True)
    roots = [runtime / name for name in ('libavcodec.so.63', 'libavformat.so.63',
             'libavutil.so.61', 'libvpl.so.2', 'libmfx-gen.so.1.2')]
    required_dynamic_roots={path.resolve(strict=True) for path in roots+[Path(driver)]}
    pending = roots + [Path(driver), Path(loader)]
    files = {}
    while pending:
        path = pending.pop().resolve(strict=True)
        if path in files:
            continue
        if not (path.is_relative_to(runtime) or path.is_relative_to(system)):
            raise ValueError('Dependency outside isolated runtime/target system')
        if not path.is_file():
            raise ValueError('Regular code artifact required')
        data = subprocess.check_output(['readelf', '-d', str(path)], text=True)
        dependencies=needed_names(data)
        if path in required_dynamic_roots and not dependencies:
            raise ValueError('Known shared runtime root requires dependencies')
        files[path] = code_fingerprint(path)[1]
        for name in dependencies:
            if '/' in name:
                raise ValueError('Unexpected absolute dependency')
            candidates = [runtime / name, system / name]
            resolved = next((candidate for candidate in candidates if candidate.exists()), None)
            if resolved is None:
                raise ValueError('Unresolved target dependency')
            pending.append(resolved)
    if len({path.name for path in files}) != len(files):
        raise ValueError('Ambiguous canonical code basename')
    return {'files': {path.name: {'path': str(path), 'sha256': digest}
                      for path, digest in sorted(files.items())}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ('runtime', 'driver', 'loader', 'output'):
        parser.add_argument('--' + key, type=Path, required=True)
    args = parser.parse_args()
    os.umask(0o077)
    if args.output.exists() or args.output.is_symlink() or not args.output.is_absolute():
        raise ValueError('Fresh absolute private output required')
    result={'pass':False,'gpu_work':False}
    try:
        limits=resources()
        if limits['memory_limit_bytes']!=536870912 or limits['swap_limit_bytes']!=0 or not 0<limits['cpu_limit']<=1:
            raise ValueError('Required closure preparation resource limits absent')
        manifest=closure(args.runtime,args.driver,args.loader)
        with args.output.open('x') as stream:
            json.dump(manifest,stream)
        args.output.chmod(0o600)
        result.update({'pass':True,'code_files':len(manifest['files'])})
    except Exception as error:
        result['error_type']=type(error).__name__
    finally:
        try:
            result['resources']=resources();r=result['resources']
            if not 0<r['peak_memory_bytes']<=r['memory_limit_bytes'] or any(r['memory_events'].values()) or r['swap_current_bytes'] or r['swap_peak_bytes']:
                result['pass']=False
        except Exception:
            result.update({'pass':False,'resource_evidence_missing':True})
        print(json.dumps(result))
    return 0 if result['pass'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
