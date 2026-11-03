#!/usr/bin/env python3
"""Plays the iPhone's remote against big-fella-remote, with pyatv (MIT), which
implements the client side of Companion Link: pairs with the PIN the daemon
shows (read off its control socket, as the home screen would), connects
again (pair-verify with the stored keys), then sends the remote's buttons,
swipes, the volume buttons and keyboard text. It plays the home screen too:
it offers a text field on the control socket and applies the typing the
daemon passes on, as services/Remote.qml does.

    fake_iphone.py HOST PORT CONTROL_SOCKET [--scan] [--no-input]

--no-input sends no buttons, swipes or volume (a box whose screen someone
else is using): pairing, verify and the keyboard only.

Prints what it did and what the control socket said, one line each, and
exits non-zero if a step failed. The keys themselves are checked on the
virtual keyboard by run.sh (evtest).
"""

import asyncio
import json
import sys

import pyatv
from pyatv import conf
from pyatv.const import Protocol, PairingRequirement


class Shell:
    """The home screen's side of the control socket."""

    def __init__(self, path):
        self.path = path
        self.state = None
        self.events = []
        self.text = ""
        self.changed = asyncio.Event()

    async def start(self):
        self.reader, self.writer = await asyncio.open_unix_connection(self.path)
        asyncio.get_running_loop().create_task(self._read())

    async def _read(self):
        while True:
            line = await self.reader.readline()
            if not line:
                return
            msg = json.loads(line)
            if "state" in msg:
                self.state = msg["state"]
            elif msg.get("event") == "text":
                if msg.get("replace") is not None:
                    self.text = msg["replace"]
                if msg.get("delete"):
                    self.text = self.text[: max(0, len(self.text) - msg["delete"])]
                self.text += msg.get("insert") or ""
                self.events.append(msg)
                # As the shell does: the field's text back to the daemon.
                await self.send({"cmd": "keyboard", "open": True, "field": 1, "text": self.text, "title": "Search"})
            else:
                self.events.append(msg)
            self.changed.set()

    async def send(self, obj):
        self.writer.write((json.dumps(obj) + "\n").encode())
        await self.writer.drain()

    async def wait(self, pred, timeout=10):
        async def loop():
            while not pred():
                self.changed.clear()
                await self.changed.wait()
        await asyncio.wait_for(loop(), timeout)


def step(name, ok=True, detail=""):
    print(f"{'ok  ' if ok else 'FAIL'} {name}{': ' + detail if detail else ''}", flush=True)
    if not ok:
        sys.exit(1)


async def main():
    host, port, control = sys.argv[1], int(sys.argv[2]), sys.argv[3]
    loop = asyncio.get_running_loop()
    shell = Shell(control)
    await shell.start()
    await shell.wait(lambda: shell.state is not None)
    step("control socket", True, f"name {shell.state['name']!r}, pairing {shell.state['pairing']}")

    if "--scan" in sys.argv:
        def companion(found):
            return [s for d in found for s in d.services if s.protocol == Protocol.Companion]

        # A query to the host (pyatv's own way), then multicast, as an
        # iPhone browses.
        uni = companion(await pyatv.scan(loop, hosts=[host], timeout=5))
        step("mDNS: answered a query to the host", bool(uni),
             f"port {uni[0].port}, rpMd {uni[0].properties.get('rpmd')}" if uni else "")
        multi = companion([d for d in await pyatv.scan(loop, timeout=5) if str(d.address) == host])
        step("mDNS: answered a multicast browse", bool(multi),
             f"port {multi[0].port}, rpFl {multi[0].properties.get('rpfl')}" if multi else "")

    def config(credentials=None):
        c = conf.AppleTV(host, "big-fella")
        c.add_service(conf.ManualService(
            "big-fella-remote", Protocol.Companion, port, {},
            credentials=credentials, pairing_requirement=PairingRequirement.Mandatory))
        return c

    async def refused(name, credentials):
        """Connecting with these credentials gets no remote session."""
        try:
            atv = await asyncio.wait_for(pyatv.connect(config(credentials), loop), 10)
        except Exception as e:  # noqa: BLE001
            step(name, True, f"{type(e).__name__}: {e}")
            return
        try:
            await asyncio.wait_for(atv.remote_control.up(), 5)
            step(name, False, "it got a session")
        except Exception as e:  # noqa: BLE001
            step(name, True, type(e).__name__)
        finally:
            atv.close()

    # A phone that never paired (made-up keys).
    await refused("an unpaired phone is refused", ":".join(["00" * 32, "11" * 32, "22" * 8, "33" * 8]))

    # Pairing: the PIN from the "screen".
    pairing = await pyatv.pair(config(), Protocol.Companion, loop, name="pyatv iPhone")
    await pairing.begin()
    await shell.wait(lambda: shell.state.get("request") is not None)
    pin = shell.state["request"]["pin"]
    step("pair-setup M1: the TV shows a PIN", len(pin) == 4 and pin.isdigit(),
         f"{shell.state['request']['seconds']} s to type it")
    pairing.pin(int(pin))
    await pairing.finish()
    step("pair-setup M3-M6 with that PIN", pairing.has_paired)
    credentials = pairing.service.credentials
    await pairing.close()
    await shell.wait(lambda: shell.state["request"] is None and len(shell.state["phones"]) >= 1)
    step("paired phone listed", True, json.dumps([p["name"] for p in shell.state["phones"]]))

    # A wrong PIN is refused.
    bad = await pyatv.pair(config(), Protocol.Companion, loop)
    await asyncio.sleep(3.2)  # the back-off after a failure (none yet, but harmless)
    await bad.begin()
    await shell.wait(lambda: shell.state.get("request") is not None)
    right = shell.state["request"]["pin"]
    bad.pin(int(right) ^ 1 if right != "0001" else 2)
    try:
        await bad.finish()
        step("a wrong PIN is refused", not bad.has_paired)
    except Exception as e:  # noqa: BLE001
        step("a wrong PIN is refused", True, type(e).__name__)
    await bad.close()

    # Again with the stored keys: pair-verify, the session, the remote.
    atv = await pyatv.connect(config(credentials), loop)
    rc = atv.remote_control
    await shell.wait(lambda: shell.state["remotes"] >= 1)
    step("pair-verify with the stored keys", True, f"{shell.state['remotes']} remote(s) connected")
    if "--no-input" not in sys.argv:
        for name in ["up", "down", "left", "right", "select", "menu", "home", "play_pause"]:
            await getattr(rc, name)()
            await asyncio.sleep(0.15)
            step(f"button {name}")
        # The ±10 s buttons (media skip).
        await rc.skip_forward()
        await rc.skip_backward()
        step("skip forward and back")
        await asyncio.sleep(0.2)
        # Swipes on the touch area (1000 × 1000, y down): right 1 step, down 2.
        await atv.touch.swipe(300, 500, 520, 500, 200)
        await asyncio.sleep(0.2)
        await atv.touch.swipe(500, 200, 500, 560, 300)
        await asyncio.sleep(0.2)
        step("swipes")
        # The volume buttons (no speakerd here: the volume keys).
        await atv.audio.volume_up()
        await atv.audio.volume_down()
        step("volume up and down", True, f"GetVolume says {atv.audio.volume:.0f}")

    # The keyboard: the shell offers a field; pyatv sees it focused and types.
    await shell.send({"cmd": "keyboard", "open": True, "field": 1, "text": "the ", "title": "Search"})
    await shell.wait(lambda: shell.state["keyboard"])
    await asyncio.sleep(0.3)
    got = await atv.keyboard.text_get()
    step("_tiStart: the field's text", got == "the ", repr(got))
    shell.text = "the "
    await atv.keyboard.text_append("wire ✓")
    await shell.wait(lambda: shell.text == "the wire ✓")
    step("typing reaches the field (unicode too)", True, repr(shell.text))
    await atv.keyboard.text_set("Sopranos")
    await shell.wait(lambda: shell.text == "Sopranos")
    step("replacing the text", True, repr(shell.text))
    await atv.keyboard.text_clear()
    await shell.wait(lambda: shell.text == "")
    step("clearing it", True)
    focus = atv.keyboard.text_focus_state
    await shell.send({"cmd": "keyboard", "open": False})
    await asyncio.sleep(0.5)
    step("_tiStopped: the phone's keyboard goes", atv.keyboard.text_focus_state != focus,
         f"{focus} -> {atv.keyboard.text_focus_state}")

    atv.close()
    await asyncio.sleep(0.3)

    # Forget the phone from Settings: it can't verify any more.
    pid = shell.state["phones"][0]["id"]
    await shell.send({"cmd": "forget", "phone": pid})
    await shell.wait(lambda: not shell.state["phones"])
    await refused("a forgotten phone is refused", credentials)
    print("events:", json.dumps(shell.events), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
