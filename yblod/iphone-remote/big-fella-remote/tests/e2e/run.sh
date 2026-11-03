#!/bin/sh
# In a privileged Linux container with /dev/uinput: start the daemon, find
# its keyboard, record it with evtest while fake_iphone.py plays the iPhone,
# then check the keys came in the order pressed.
set -eu
BIN=$1
cat > /tmp/e2e.toml <<CFG
name = "big-fella e2e"
state_dir = "/tmp/state"
control_socket = "/tmp/control.sock"
[speaker]
enabled = false
CFG
RUST_LOG=info "$BIN" --config /tmp/e2e.toml > /tmp/daemon.log 2>&1 &
sleep 1
dev() { awk -v n="$1" '/^N: Name=/{name=$0} /^H: Handlers=/{ if (name == "N: Name=\"" n "\"") { match($0, /event[0-9]+/); print "/dev/input/" substr($0, RSTART, RLENGTH) } }' /proc/bus/input/devices; }
KBD=$(dev "big-fella iPhone remote")
echo "keyboard: $KBD"
# Docker's /dev was filled in when the container started: a device made
# since has no node yet.
if [ ! -e "$KBD" ]; then
  mknod "$KBD" c $(tr ':' ' ' < "/sys/class/input/$(basename "$KBD")/dev")
fi
timeout -s INT 90 stdbuf -oL evtest "$KBD" > /tmp/kbd.log 2>&1 &
sleep 0.5
IP=$(getent hosts "$(hostname)" | awk '{print $1; exit}')
status=0
/tmp/venv/bin/python /e2e/fake_iphone.py "$IP" 49153 /tmp/control.sock --scan || status=$?
sleep 1
pkill -INT evtest || :
head -3 /tmp/kbd.log
sleep 0.5
echo "== keys pressed (value 1), in order"
got=$(grep -E "^Event:.*EV_KEY.*value 1$" /tmp/kbd.log | sed -E 's/.*\((KEY_[A-Z0-9_]+)\).*/\1/' | tr '\n' ' ')
echo "$got"
want="KEY_UP KEY_DOWN KEY_LEFT KEY_RIGHT KEY_ENTER KEY_ESC KEY_HOMEPAGE KEY_PLAYPAUSE KEY_FASTFORWARD KEY_REWIND KEY_RIGHT KEY_DOWN KEY_DOWN KEY_VOLUMEUP KEY_VOLUMEDOWN "
if [ "$got" = "$want" ]; then echo "ok   the virtual keyboard's keys"; else echo "FAIL the virtual keyboard's keys: want $want"; status=1; fi
echo "== every key event"; grep -cE "^Event:.*EV_KEY" /tmp/kbd.log
echo "== daemon log"; sed "s/\x1b\[[0-9;]*m//g" /tmp/daemon.log
exit $status
