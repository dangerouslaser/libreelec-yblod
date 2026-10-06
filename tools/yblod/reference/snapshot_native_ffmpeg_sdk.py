"""Preserve the exact VAAPI-only FFmpeg SDK state before experimental rebuild.

Code/build artifacts only. Never restores, deletes, changes SDK files or starts
playback. A fresh private archive and sidecar manifest are required.
"""
import argparse
import hashlib
import json
from pathlib import Path
import tarfile

BASE = "build.LibreELEC-Generic.x86_64-13.0-devel"
FAMILIES = ("libavcodec", "libavdevice", "libavfilter", "libavformat",
            "libavutil", "libswresample", "libswscale", "libpostproc")


def digest(path):
    sha = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            sha.update(chunk)
    return sha.hexdigest()


def snapshot(source_root, archive):
    root, output = Path(source_root), Path(archive)
    if not root.is_absolute() or root.is_symlink() or not root.is_dir():
        raise ValueError("source root must be an existing absolute directory")
    if not output.is_absolute() or output.name != "baseline-ffmpeg-sdk.tar":
        raise ValueError("use the exact baseline-ffmpeg-sdk.tar private archive name")
    if not output.parent.is_dir() or output.parent.is_symlink():
        raise ValueError("archive parent must already exist and not be a symlink")
    manifest = output.with_suffix(".json")
    if output.exists() or output.is_symlink() or manifest.exists() or manifest.is_symlink():
        raise ValueError("archive and manifest must be fresh; nothing is overwritten")
    base = root / BASE
    ffmpeg = base / "build/ffmpeg-9.0.2"
    config = ffmpeg / "config.h"
    text = config.read_text()
    if "#define CONFIG_LIBVPL 0\n" not in text or "#define CONFIG_VAAPI 1\n" not in text:
        raise ValueError("baseline must still be VAAPI enabled and VPL disabled")
    sdk = base / "toolchain/x86_64-libreelec-linux-gnu/sysroot/usr"
    items = [ffmpeg, base / ".stamps/ffmpeg", root / "packages/multimedia/ffmpeg/package.mk"]
    libraries = []
    for family in FAMILIES:
        headers, pc = sdk / "include" / family, sdk / "lib/pkgconfig" / (family + ".pc")
        matches = sorted((sdk / "lib").glob(family + ".so*"))
        required = family != "libpostproc"
        if required and (not headers.is_dir() or not pc.is_file() or not matches):
            raise ValueError("missing baseline SDK family: " + family)
        if headers.exists():
            items.append(headers)
        if pc.exists():
            items.append(pc)
        for path in matches:
            if not (path.is_file() or path.is_symlink()):
                raise ValueError("unexpected library entry")
            if path.is_symlink() and not path.resolve().is_relative_to(root.resolve()):
                raise ValueError("library symlink escapes the SDK source root")
            items.append(path)
            libraries.append({"name": path.name, "sha256": digest(path),
                              "symlink": str(path.readlink()) if path.is_symlink() else None})
    for path in items:
        path.relative_to(root)
        if not path.exists() or path.is_symlink() and path.is_dir():
            raise ValueError("invalid baseline source entry")
    # Exclusive creation prevents replacement of any earlier rollback evidence.
    with tarfile.open(output, "x") as store:
        for path in items:
            store.add(path, arcname=str(path.relative_to(root)), recursive=True)
    record = {"schema": "yblod.ffmpeg-sdk-baseline.v1", "complete": True,
              "archive_sha256": digest(output), "archive_bytes": output.stat().st_size,
              "baseline_config_sha256": digest(config),
              "package_recipe_sha256": digest(root / "packages/multimedia/ffmpeg/package.mk"),
              "vaapi_enabled": True, "libvpl_enabled": False,
              "configured_ffmpeg_tree_and_stamps_preserved": True,
              "headers_pkgconfig_and_all_library_versions_preserved": True,
              "libraries": libraries, "automatic_restore": False}
    with manifest.open("x") as stream:
        json.dump(record, stream, indent=2)
        stream.write("\n")
    return record


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", required=True)
    parser.add_argument("--archive", required=True)
    args = parser.parse_args()
    result = snapshot(args.source_root, args.archive)
    print(json.dumps({key: value for key, value in result.items() if key != "libraries"}))
