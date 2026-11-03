#!/bin/sh
# End to end on Linux, from any machine with Docker: builds big-fella-remote
# in a privileged container (for /dev/uinput), runs it with mDNS on, and
# plays the iPhone with pyatv (tests/e2e/fake_iphone.py: found over mDNS,
# paired with the PIN off the control socket, verified, then buttons,
# swipes, volume and typing). run.sh checks the virtual keyboard's events.
#
# JOBS and MEM bound the build (default 3 and 3g: build hosts run other
# things).
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
CRATE=$(cd "$HERE/../.." && pwd)
docker run --rm --privileged --memory "${MEM:-3g}" --cpus "${JOBS:-3}" \
    -v "$CRATE":/src/big-fella-remote:ro -v "$CRATE/../bf-daemon":/src/bf-daemon:ro -v "$HERE":/e2e:ro \
    -v big-fella-remote-cargo:/usr/local/cargo/registry \
    -w /src/big-fella-remote -e CARGO_TARGET_DIR=/tmp/target -e CARGO_BUILD_JOBS="${JOBS:-3}" \
    rust:1-slim sh -c '
        apt-get -qq update >/dev/null
        DEBIAN_FRONTEND=noninteractive apt-get install -y -qq --no-install-recommends evtest python3 python3-venv procps >/dev/null
        python3 -m venv /tmp/venv && /tmp/venv/bin/pip -q install pyatv "srptools==1.0.1" 2>&1 | grep -v notice || :
        cargo build --release --locked -q
        /e2e/run.sh /tmp/target/release/big-fella-remote'
