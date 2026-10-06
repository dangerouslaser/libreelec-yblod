"""Inject only the session-creation dependency in the actual allocator registration."""
import pathlib
source = pathlib.Path('/opt/ffmpeg-source/libavcodec/qsv.c').read_text()
needle = '''ret = ff_qsv_init_session_device(avctx, &session,
                                     frames_ctx->device_ref, load_plugins, gpu_copy);'''
assert source.count(needle) == 1
source = source.replace(needle, needle.replace('ff_qsv_init_session_device', 'fixture_session_device'))
pathlib.Path('/tmp/qsv_allocator_fixture.c').write_text(source)
