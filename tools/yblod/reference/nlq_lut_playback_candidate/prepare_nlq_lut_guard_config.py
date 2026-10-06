#!/usr/bin/env python3
"""Create PRIVATE content pins on the test host; never publish its output."""
import json
import os
from pathlib import Path
import sys
from run_nlq_lut_guard import LIBRARIES, ROLES, digest, require

def main():
    require(len(sys.argv) in (12,14,15,16), "usage: OUTPUT_JSON LUT_MODE SEQUENCE BINARY SHADER INSTRUCTIONS BL_Y BL_CB BL_CR GUIDE P010 [WARMUPS SAMPLES [FREQUENCY [KODI_STATE]]]")
    target = Path(sys.argv[1])
    require(target.is_absolute() and not target.exists(), "fresh absolute output path required")
    require(sys.argv[2] in ("0", "1") and sys.argv[3] in ("0", "1"), "flags must be zero or one")
    artifacts = {}
    for role, value in zip(ROLES, sys.argv[4:]):
        path = Path(value)
        require(path.is_absolute() and path.is_file() and not path.is_symlink(), "regular absolute input required")
        artifacts[role] = {"path": str(path), "sha256": digest(path)}
    result = {"schema": "yblod.nlq-lut-playback-options-private-guard.v1", "lut_mode": int(sys.argv[2]),
              "metadata_sequence": sys.argv[3] == "1", "artifacts": artifacts,
              "libraries": [{"path": path, "sha256": digest(path)} for path in LIBRARIES]}
    if len(sys.argv)>=14:
        warmups=int(sys.argv[12]); samples=int(sys.argv[13])
        require(1 <= warmups <= 32 and 1 <= samples <= 32 and (sys.argv[3]=="0" or warmups>=2), "iterations exceed probe bounds")
        result.update(warmups=warmups,samples=samples)
    if len(sys.argv)>=15:
        require(sys.argv[14] in ("0","1"), "frequency must be zero or one")
        result["frequency"]=sys.argv[14]=="1"
    if len(sys.argv)==16:
        require(sys.argv[15] in ("active","inactive"), "Kodi state must be active or inactive")
        result["kodi_state"]=sys.argv[15]
    os.umask(0o077)
    with target.open("x") as stream:
        json.dump(result, stream, indent=2); stream.write("\n")
    print(digest(target))

if __name__ == "__main__":
    main()
