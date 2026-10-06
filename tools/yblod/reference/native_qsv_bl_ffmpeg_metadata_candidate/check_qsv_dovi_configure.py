"""Run the patched configure against cached FFmpeg sources in disposable dirs."""
import os
import pathlib
import subprocess

root = pathlib.Path('/tmp/qsv-dovi-fixture')
for enabled in (False, True):
    work = root / ('configure-gpl3' if enabled else 'configure-no-gpl')
    work.mkdir()
    (work / 'src').symlink_to('/opt/ffmpeg-source', target_is_directory=True)
    args = ['sh', str(root / 'configure'), '--disable-everything', '--disable-autodetect',
            '--disable-x86asm', '--disable-programs', '--disable-doc',
            '--enable-decoder=hevc_qsv', '--enable-libvpl']
    if enabled:
        args += ['--enable-gpl', '--enable-version3']
    subprocess.run(args, cwd=work, check=True, stdout=subprocess.DEVNULL,
                   env={**os.environ, 'CCACHE_DISABLE': '1'})
    config = (work / 'config.h').read_text()
    components = (work / 'config_components.h').read_text()
    assert '#define CONFIG_HEVC_QSV_DECODER 1' in components
    assert '#define CONFIG_DOVI_RPUDEC ' + str(int(enabled)) in config
    if enabled:
        assert '#define CONFIG_HEVCPARSE 1' in config
    print('actual_configure_' + ('gpl3' if enabled else 'no_gpl') + '_dependencies_PASS')
