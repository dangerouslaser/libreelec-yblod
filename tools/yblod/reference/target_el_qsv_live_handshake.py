"""Live target proof for a reviewed C probe child, not a standalone launcher."""
import json
import os
from pathlib import Path
import re
import stat

from collect_el_qsv_target_identity import fingerprint, mapped_libraries, process_gpu_client, is_mapped_code


def process_record(pid):
    if type(pid) is not int or pid<=0:raise ValueError('Actual positive process PID required')
    root=Path('/proc')/str(pid)
    text=(root/'stat').read_text()
    fields=text[text.rfind(')')+2:].split()
    if len(fields)<20:raise ValueError('Incomplete actual process identity')
    return dict(pid=pid,ppid=int(fields[1]),start_ticks=int(fields[19]),
                executable=str((root/'exe').resolve(strict=True)),
                argv=[os.fsdecode(value) for value in (root/'cmdline').read_bytes().split(b'\0') if value])


def unit_children(unit_pid):
    rows=[]
    for entry in Path('/proc').iterdir():
        if not entry.name.isdigit():continue
        try:record=process_record(int(entry.name))
        except (FileNotFoundError,ProcessLookupError):continue
        if record['ppid']==unit_pid:rows.append(record)
    return rows


def mapped_probe(pid,binary,expected_sha):
    binary=Path(binary).resolve(strict=True)
    observed=False
    for line in (Path('/proc')/str(pid)/'maps').read_text().splitlines():
        fields=line.split(None,5)
        if len(fields)==6 and fields[5].startswith('/'):
            if fields[5].endswith(' (deleted)'):
                if fields[5][:-10]==str(binary):raise ValueError('Deleted probe mapping')
                continue
            if Path(fields[5]).resolve(strict=True)==binary:observed=True
    if not observed or fingerprint(binary)[1]!=expected_sha:raise ValueError('Actual probe code mapping mismatch')
    return True


def audit_mapped_code(child,binary,expected_sha,private_output,expected_code_root):
    """Private code-path inventory only, before strict admission; never raw maps."""
    output=Path(private_output)
    if not output.is_absolute() or output.exists() or output.is_symlink():raise ValueError('Fresh private code audit required')
    root=Path(expected_code_root).resolve(strict=True)
    rows=[]
    for line in (Path('/proc')/str(child['pid'])/'maps').read_text().splitlines():
        fields=line.split(None,5)
        if len(fields)!=6 or not fields[5].startswith('/'):continue
        deleted=fields[5].endswith(' (deleted)')
        path=Path(fields[5][:-10] if deleted else fields[5])
        if not is_mapped_code(path,fields[1]):continue
        if path==Path(binary).resolve(strict=True) and not deleted:continue
        canonical=path.resolve(strict=not deleted)
        under_root=canonical.is_relative_to(root)
        identity=None
        # Never hash or open unexpected/outside paths. Stat only SDK code.
        if under_root and not deleted:
            info=canonical.stat()
            if stat.S_ISREG(info.st_mode):identity=[getattr(info,key) for key in ('st_dev','st_ino','st_size','st_mtime_ns','st_ctime_ns')]
        item=dict(path=str(canonical),deleted=deleted,under_expected_code_root=under_root,stat_identity=identity)
        if item not in rows:rows.append(item)
    summary=dict(canonical_so_count=len(rows),under_expected_code_root_count=sum(row['under_expected_code_root'] for row in rows),
        outside_expected_code_root_count=sum(not row['under_expected_code_root'] for row in rows),deleted_map_count=sum(row['deleted'] for row in rows))
    identity=lambda value:[getattr(value,key) for key in ('st_dev','st_ino','st_size','st_mtime_ns','st_ctime_ns')]
    record=dict(process={key:child[key] for key in ('pid','ppid','start_ticks','executable')},
        expected_probe_binary=str(Path(binary).resolve(strict=True)),expected_probe_code_sha256=expected_sha,
        probe_file_identity=identity(Path(binary).stat()),loader_file_identity=identity(Path(child['executable']).stat()),
        mapped_code=rows,summary=summary)
    with output.open('x') as stream:json.dump(record,stream)
    output.chmod(0o600)
    return summary


def acknowledge_unit_child(ready,ack,nonce,unit_pid,unit_start_ticks,loader,binary,
                           expected_binary_sha,expected_argv,node,runtime_files,driver,
                           private_library_audit=None,expected_code_root=None):
    """Call while the child holds its genuine QSV helper/device alive at ready."""
    if not isinstance(nonce,str) or not re.fullmatch('[a-f0-9]{64}',nonce):raise ValueError('Fresh nonce required')
    if not isinstance(expected_binary_sha,str) or not re.fullmatch('[a-f0-9]{64}',expected_binary_sha):raise ValueError('Expected probe code digest required')
    ready,ack=Path(ready),Path(ack)
    if not ready.is_absolute() or not ack.is_absolute() or ready==ack or ack.exists() or ack.is_symlink():raise ValueError('Fresh separate private checkpoint paths required')
    info=ready.lstat()
    if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode)!=0o600:raise ValueError('Private regular checkpoint required')
    checkpoint=json.loads(ready.read_text())
    if set(checkpoint)!={'pid','nonce'} or type(checkpoint['pid']) is not int or checkpoint['pid']<=0 or checkpoint['nonce']!=nonce:raise ValueError('Exact private checkpoint required')
    parent=process_record(unit_pid)
    if type(unit_start_ticks) is not int or unit_start_ticks<=0 or parent['start_ticks']!=unit_start_ticks:raise ValueError('Unit process generation changed')
    children=unit_children(unit_pid)
    if len(children)!=1 or children[0]['pid']!=checkpoint['pid']:raise ValueError('Exactly one actual unit child must own checkpoint')
    child=children[0]
    if child['executable']!=str(Path(loader).resolve(strict=True)) or child['argv']!=expected_argv:raise ValueError('Actual loader/probe invocation differs')
    if mapped_probe(child['pid'],binary,expected_binary_sha) is not True:raise ValueError('Actual probe mapping proof required')
    if private_library_audit is not None:
        if expected_code_root is None:raise ValueError('Expected code root required for private audit')
        audit_mapped_code(child,binary,expected_binary_sha,private_library_audit,expected_code_root)
    clients=process_gpu_client(child['pid'],node)
    libraries=mapped_libraries(child['pid'],runtime_files,driver,verified_probe=binary)
    if not clients or libraries is not True:raise ValueError('Actual live GPU client and complete mapped closure required')
    # Recheck process generations and checkpoint after inspecting live maps/fdinfo.
    identity=lambda value:tuple(getattr(value,key) for key in ('st_dev','st_ino','st_mode','st_uid','st_size','st_mtime_ns','st_ctime_ns'))
    if process_record(unit_pid)!=parent or process_record(child['pid'])!=child or identity(ready.lstat())!=identity(info) or json.loads(ready.read_text())!=checkpoint:
        raise ValueError('Live proof changed before acknowledgement')
    descriptor=os.open(ack,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    with os.fdopen(descriptor,'wb') as stream:stream.write(nonce.encode('ascii'))
    return dict(probe_pid=child['pid'],probe_start_ticks=child['start_ticks'],
                actual_client_rows=clients,actual_libraries_verified=libraries,
                actual_probe_mapping_verified=True,live_child_association_verified=True)
