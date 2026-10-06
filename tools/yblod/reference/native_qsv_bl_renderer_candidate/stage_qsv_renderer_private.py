"""Apply a renderer-only draft to disposable copies; never to the SDK tree."""
import pathlib
import shutil
import subprocess
import sys

kodi = pathlib.Path(sys.argv[1]).resolve(strict=True)
reference = pathlib.Path(sys.argv[2]).resolve(strict=True)
work = pathlib.Path(sys.argv[3])
work.mkdir(exist_ok=False)
renderer = pathlib.Path('xbmc/cores/VideoPlayer/VideoRenderers')
files = [renderer / 'HwDecRender' / name for name in
         ('VaapiEGL.cpp', 'VaapiEGL.h', 'RendererVAAPIGLES.cpp', 'RendererVAAPIGLES.h')]
files += [renderer / name for name in ('DVBridgeGLES.cpp', 'DVBridgeGLES.h')]
(work / 'renderer-baseline').mkdir()
for relative in files:
    destination = work / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(kodi / relative, destination)
    shutil.copyfile(kodi / relative, work / 'renderer-baseline' / relative.name)
subprocess.run(['patch', '--batch', '--fuzz=0', '-p1', '-i',
                str(reference / 'qsv-bl-renderer-source-only.patch')], cwd=work, check=True)
for relative in files:
    shutil.copyfile(work / relative, work / relative.name)
buffer = reference.parent / 'native_qsv_bl_buffer_candidate'
for name in ('QsvMappedBuffer.cpp', 'QsvMappedBuffer.h'):
    shutil.copyfile(buffer / name, work / name)
for relative, source in (
        ('cores/VideoPlayer/Buffers/QsvMappedBuffer.h', work / 'QsvMappedBuffer.h'),
        ('cores/VideoPlayer/VideoRenderers/DVBridgeGLES.h', work / 'DVBridgeGLES.h')):
    destination = work / 'overrides' / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)
