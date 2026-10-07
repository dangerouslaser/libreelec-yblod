"""Reuse the proven observer with only additive EL decoder log collection.

No existing observer file is edited. Fail before playback if its two known
collection lists change; route validation remains the controller's job.
"""
from pathlib import Path


def with_el_markers(source):
    marker = "'DVBridge native composer:',"
    if source.count(marker) != 2:
        raise ValueError('Observer collection layout changed; review EL marker integration')
    return source.replace(marker, marker + " 'DV FEL decoder:', 'DVBridge BL QSV:',")


def main():
    base = Path(__file__).with_name('observe_native_movie.py')
    source = with_el_markers(base.read_text())
    namespace = dict(__name__='__main__', __file__=str(base))
    exec(compile(source, str(base), 'exec'), namespace)


if __name__ == '__main__':
    main()
