"""Prepare only EL helper patches21/22 atop verified19/20; default dry preparation."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
from prepare_qsv_el_kodi_build import BUILD, FILES, NEW, digest, validate_prepared

PATCHES=('kodi-9999-yblod-21-qsv-el-headers.patch','kodi-9999-yblod-22-qsv-el-frame-timebase.patch')
PATCH_SHA={PATCHES[0]:'e310ae06f81e7d8c006143494fad07bdb3401d0c19aad13b039892c180838552',
           PATCHES[1]:'ccfcc29438283c0c8c647d303390f3979d13609720a832ac4fa306310475efea'}
BUILD_FILES=('kodi.bin','build.ninja','CMakeFiles/rules.ninja','CMakeCache.txt','compile_commands.json')
HELPER='tools/dvbridge/dvbridge_fel.c'
EXPECTED_HELPER_SHA='fed8e6e9c3eb4a53108cfe49778959c6df794a027aa646e57145d03a97803df1'


class PartialPreparationFailure(RuntimeError):
    def __init__(self,report):
        super().__init__('Source application failed; preserved backup requires inspection')
        self.report=report


def prepare(kodi,recipe,receipt,expected_binary_sha,backup_parent,apply_source):
    validate_prepared(kodi,receipt)
    build=kodi/'.x86_64-libreelec-linux-gnu'
    if digest(build/'kodi.bin')!=expected_binary_sha:
        raise ValueError('Retained exact candidate binary required')
    build_before={name:digest(build/name) for name in BUILD_FILES}
    backup=Path(tempfile.mkdtemp(prefix='qsv-el-pre21-',dir=backup_parent))
    source=backup/'source'
    for name in (*FILES,NEW):
        target=source/name;target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(kodi/name,target)
    for name in BUILD_FILES:
        target=backup/'build'/name;target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(build/name,target)
        if digest(target)!=build_before[name] or digest(build/name)!=build_before[name]:
            raise ValueError('Build artifact changed during preserved backup')
    patch_digests={}
    for name in PATCHES:
        patch=recipe/'packages/mediacenter/kodi/patches'/name
        patch_digests[name]=digest(patch)
        if patch_digests[name]!=PATCH_SHA[name]:raise ValueError('Exact reviewed patch required')
        subprocess.run(['patch','--batch','--fuzz=0','-p1','-i',str(patch)],cwd=source,check=True)
    if digest(source/HELPER)!=EXPECTED_HELPER_SHA:
        raise ValueError('Patched helper differs from raw-qualified source')
    for name in (*FILES,NEW):
        if name!=HELPER and digest(source/name)!=digest(kodi/name):
            raise ValueError('Non-helper source changed')
    validate_prepared(kodi,receipt)
    if any(digest(build/name)!=build_before[name] for name in BUILD_FILES):
        raise ValueError('Build artifact changed during isolated preparation')
    if apply_source:
        validate_prepared(kodi,receipt)
        if digest(build/'kodi.bin')!=expected_binary_sha:
            raise ValueError('Retained candidate changed before source apply')
        attempted=False
        try:
            for name in PATCHES:
                patch=recipe/'packages/mediacenter/kodi/patches'/name
                if digest(patch)!=patch_digests[name]:raise ValueError('Reviewed patch changed')
                subprocess.run(['patch','--batch','--fuzz=0','-p1','--dry-run','-i',str(patch)],cwd=kodi,check=True)
                attempted=True
                subprocess.run(['patch','--batch','--fuzz=0','-p1','-i',str(patch)],cwd=kodi,check=True)
            if any(digest(kodi/name)!=digest(source/name) for name in (*FILES,NEW)):
                raise ValueError('Actual applied source differs from isolated proof')
            if any(digest(build/name)!=build_before[name] for name in BUILD_FILES):
                raise ValueError('Build artifact changed during source application')
        except Exception as error:
            raise PartialPreparationFailure(dict(source_applied=False,source_application_failed=True,
                partial_source_application_possible=attempted,backup_directory=str(backup),
                build_started=False,error_type=type(error).__name__)) from error
    return dict(source_applied=apply_source,backup_directory=str(backup),
                baseline_binary_sha256=expected_binary_sha,
                isolated_source_sha256={name:digest(source/name) for name in (*FILES,NEW)},
                engine_sha256=receipt['engine_sha256'],patch_sha256=patch_digests,
                retained_build_artifact_sha256=build_before,
                only_el_helper_changed=True,build_started=False,hardware_playback_qualified=False)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('sdk-project','recipe-root','baseline-receipt','backup-parent','report'):
        parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--expected-binary-sha256',required=True)
    parser.add_argument('--apply-source',action='store_true')
    args=parser.parse_args()
    if args.report.exists() or args.report.is_symlink():raise ValueError('Fresh preparation report required')
    kodi=args.sdk_project.resolve(strict=True)/BUILD/'build/kodi-22.0rc1-Piers'
    failed=False
    try:
        result=prepare(kodi,args.recipe_root.resolve(strict=True),json.loads(args.baseline_receipt.read_text()),
                       args.expected_binary_sha256,args.backup_parent.resolve(strict=True),args.apply_source)
    except PartialPreparationFailure as error:
        result=error.report;failed=True
    with args.report.open('x') as stream:json.dump(result,stream)
    print(json.dumps({'source_applied':result['source_applied'],'source_application_failed':failed,'build_started':False}))
    return 1 if failed else 0


if __name__=='__main__':raise SystemExit(main())
