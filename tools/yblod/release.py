#!/usr/bin/env python3
"""Add a built yblod image to releases/releases.json (the LibreELEC update channel list).

usage: tools/yblod/release.py <version> <target dir> [lg]
   e.g. tools/yblod/release.py 0.1 target
        tools/yblod/release.py 0.2.2 target lg    (LG edition, separate channel)

The LibreELEC settings add-on reads this file (see the LibreELEC-settings patch) and offers the
listed builds under Settings > LibreELEC > Updates. Files are downloaded from the GitHub release
"yblod-<version>", so upload the .tar and .img.gz there with the same names. Both editions of a
version share that release. The LG edition has its own channel: updating it from the standard
channel would remove the LG skin and add-on.
"""
import datetime
import hashlib
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CHANNELS = {"": "yblod-13.0", "lg": "yblod-lg-13.0"}   # "<name>-<LibreELEC version>"
ARCH = "Generic.x86_64"
URL = "https://github.com/dangerouslaser/libreelec-yblod/releases/download/"

version, target = sys.argv[1], Path(sys.argv[2])
edition = sys.argv[3] if len(sys.argv) > 3 else ""
if edition not in CHANNELS:
    sys.exit(f"unknown edition: {edition}")
CHANNEL = CHANNELS[edition]
suffix = f"-{edition}" if edition else ""
stem = f"LibreELEC-{ARCH}-13.0-yblod-{version}{suffix}"


def describe(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    stamp = datetime.datetime.fromtimestamp(os.path.getmtime(path), datetime.timezone.utc)
    return {"name": path.name, "sha256": h.hexdigest(), "size": str(path.stat().st_size),
            "subpath": f"yblod-{version}", "timestamp": stamp.strftime("%Y-%m-%d %H:%M:%S")}


entry = {"file": describe(target / f"{stem}.tar")}
image = target / f"{stem}.img.gz"
if image.exists():
    entry["image"] = describe(image)

path = ROOT / "releases/releases.json"
data = json.loads(path.read_text() or "{}")
channel = data.setdefault(CHANNEL, {
    "prettyname_regex": r"^LibreELEC-.*-yblod-([0-9]+\.[0-9]+(?:\.[0-9]+)?)" + suffix,
    "url": URL,
    "project": {},
})
releases = channel["project"].setdefault(ARCH, {"releases": {}})["releases"]
for key, existing in list(releases.items()):
    if existing["file"]["name"] == entry["file"]["name"]:
        del releases[key]
releases[str(len(releases))] = entry
# keep keys 0..n-1 in release order
channel["project"][ARCH]["releases"] = {str(i): v for i, v in enumerate(releases.values())}
path.write_text(json.dumps(data, indent=2) + "\n")
print(f"{CHANNEL}: added {entry['file']['name']} ({entry['file']['size']} bytes)")
