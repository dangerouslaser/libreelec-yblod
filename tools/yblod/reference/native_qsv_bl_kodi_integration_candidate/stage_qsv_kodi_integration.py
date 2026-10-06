"""Apply the complete source candidate only to disposable Kodi copies."""
import pathlib
import shutil
import subprocess
import sys

kodi, reference, work = map(pathlib.Path, sys.argv[1:4])
work.mkdir(exist_ok=False)
renderer = pathlib.Path('xbmc/cores/VideoPlayer/VideoRenderers')
codec = pathlib.Path('xbmc/cores/VideoPlayer/DVDCodecs/Video')
buffers = pathlib.Path('xbmc/cores/VideoPlayer/Buffers')
files = [renderer / 'HwDecRender' / name for name in
         ('VaapiEGL.cpp', 'VaapiEGL.h', 'RendererVAAPIGLES.cpp', 'RendererVAAPIGLES.h')]
files += [renderer / name for name in ('DVBridgeGLES.cpp', 'DVBridgeGLES.h')]
files += [codec / name for name in ('DVDVideoCodecFFmpeg.cpp', 'DVDVideoCodecFFmpeg.h')]
files += [buffers / 'CMakeLists.txt']
(work / 'renderer-baseline').mkdir()
for relative in files:
    destination = work / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(kodi / relative, destination)
    if relative.suffix in ('.h', '.cpp'):
        shutil.copyfile(kodi / relative, work / 'renderer-baseline' / relative.name)
subprocess.run(['patch', '--batch', '--fuzz=0', '-p1', '-i',
                str(reference.resolve() / 'qsv-bl-kodi-integration-source-only.patch')],
               cwd=work, check=True)
files += [buffers / name for name in ('QsvMappedBuffer.cpp', 'QsvMappedBuffer.h')]
for relative in files:
    if relative.suffix in ('.h', '.cpp'):
        shutil.copyfile(work / relative, work / relative.name)
        if relative.suffix == '.h':
            override = work / 'overrides' / relative.relative_to('xbmc')
            override.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(work / relative, override)
