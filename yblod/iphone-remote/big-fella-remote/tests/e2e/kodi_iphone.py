#!/usr/bin/env python3
"""Plays the iPhone's remote against big-fella-remote on a LibreELEC box, with
Kodi as the home screen (big-fella-remote-kodi): found over mDNS (beside
Avahi), paired with the PIN off the control socket, then buttons that Kodi
must act on, the phone's keyboard in Kodi's keyboard dialog, and volume;
checked through Kodi's JSON-RPC. The phone is forgotten at the end.

    kodi_iphone.py HOST PORT CONTROL_SOCKET KODI_TCP [--no-input]

CONTROL_SOCKET: the box's /run/iphone-remote/control.sock (here through
`ssh -L`). KODI_TCP: Kodi's JSON-RPC, HOST:9090 (here through `ssh -L`). Needs pyatv 0.18 with
srptools 1.0.1, as fake_iphone.py.
"""

import asyncio
import json
import sys

import pyatv
from pyatv import conf
from pyatv.const import Protocol, PairingRequirement


def step(name, ok=True, detail=""):
    print(f"{'ok  ' if ok else 'FAIL'} {name}{': ' + detail if detail else ''}", flush=True)
    if not ok:
        sys.exit(1)


class Kodi:
    """Kodi's JSON-RPC over TCP (objects back to back, notifications mixed in)."""

    def __init__(self, addr):
        import socket
        host, port = addr.rsplit(":", 1)
        self.sock = socket.create_connection((host, int(port)), timeout=5)
        self.dec = json.JSONDecoder()
        self.buf = ""
        self.n = 0

    def call(self, method, params=None):
        self.n += 1
        self.sock.sendall(json.dumps({"jsonrpc": "2.0", "id": self.n, "method": method,
                                      "params": params or {}}).encode())
        while True:
            self.buf = self.buf.lstrip()
            try:
                msg, end = self.dec.raw_decode(self.buf)
            except ValueError:
                self.buf += self.sock.recv(65536).decode()
                continue
            self.buf = self.buf[end:]
            if msg.get("id") == self.n:
                return msg.get("result")

    def window(self):
        return self.call("GUI.GetProperties", {"properties": ["currentwindow"]})["currentwindow"]

    def label(self, name):
        return self.call("XBMC.GetInfoLabels", {"labels": [name]})[name]


async def until(pred, timeout=8, every=0.25):
    end = asyncio.get_running_loop().time() + timeout
    while True:
        v = pred()
        if v:
            return v
        if asyncio.get_running_loop().time() > end:
            return v
        await asyncio.sleep(every)


class Control:
    def __init__(self, path):
        self.path = path
        self.state = None

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

    async def send(self, obj):
        self.writer.write((json.dumps(obj) + "\n").encode())
        await self.writer.drain()


async def main():
    host, port, control, url = sys.argv[1], int(sys.argv[2]), sys.argv[3], sys.argv[4]
    loop = asyncio.get_running_loop()
    kodi = Kodi(url)
    ctl = Control(control)
    await ctl.start()
    await until(lambda: ctl.state is not None)
    step("control socket", ctl.state is not None, f"name {ctl.state['name']!r}, pairing {ctl.state['pairing']}")

    found = [s for d in await pyatv.scan(loop, timeout=6) if str(d.address) == host
             for s in d.services if s.protocol == Protocol.Companion]
    step("mDNS: the box answers a multicast browse (beside Avahi)", bool(found),
         f"port {found[0].port}, rpMd {found[0].properties.get('rpmd')}" if found else "")

    def config(credentials=None):
        c = conf.AppleTV(host, "LibreELEC")
        c.add_service(conf.ManualService("remote", Protocol.Companion, port, {}, credentials=credentials,
                                         pairing_requirement=PairingRequirement.Mandatory))
        return c

    pairing = await pyatv.pair(config(), Protocol.Companion, loop, name="pyatv iPhone")
    await pairing.begin()
    await until(lambda: ctl.state.get("request"))
    pin = ctl.state["request"]["pin"]
    step("the TV shows a PIN", len(pin) == 4, pin)
    pairing.pin(int(pin))
    await pairing.finish()
    step("paired with it", pairing.has_paired)
    credentials = pairing.service.credentials
    await pairing.close()

    atv = await pyatv.connect(config(credentials), loop)
    try:
        await asyncio.sleep(1.5)  # the uinput keyboard is Kodi's by now; the session settles
        if "--no-input" not in sys.argv:
            await atv.remote_control.home()
            step("TV button: Kodi's Home", await until(lambda: kodi.window()["id"] == 10000),
                 json.dumps(kodi.window()))
            await atv.remote_control.right()
            await asyncio.sleep(0.5)
            await atv.remote_control.select()
            w = await until(lambda: kodi.window()["id"] != 10000)
            step("swipe right, then Select: Kodi opened something", bool(w), json.dumps(kodi.window()))
            await atv.remote_control.menu()
            step("Back (Menu): Kodi back at Home", await until(lambda: kodi.window()["id"] == 10000),
                 json.dumps(kodi.window()))
            v0 = kodi.call("Application.GetProperties", {"properties": ["volume"]})["volume"]
            await atv.audio.volume_down()
            v1 = await until(lambda: kodi.call("Application.GetProperties", {"properties": ["volume"]})["volume"] != v0)
            step("volume button: Kodi's volume moved", bool(v1), f"{v0} -> "
                 f"{kodi.call('Application.GetProperties', {'properties': ['volume']})['volume']}")
            await atv.audio.volume_up()

        # Kodi's keyboard dialog: Skin.SetString(iphone_remote_test) asks for
        # a string. JSON-RPC can't run a builtin, so the box opens it (the
        # caller runs kodi-send there once this line is printed).
        print("OPEN-KEYBOARD", flush=True)
        focus = await until(lambda: atv.keyboard.text_focus_state.name == "Focused", timeout=20)
        step("Kodi's keyboard dialog: the phone's keyboard comes up", bool(focus), atv.keyboard.text_focus_state.name)
        await atv.keyboard.text_set("wörld ✓")
        await asyncio.sleep(0.5)
        await atv.keyboard.text_append("\n")
        got = await until(lambda: kodi.label("Skin.String(iphone_remote_test)") == "wörld ✓")
        step("typed on the phone, Return: Kodi's string", bool(got), repr(kodi.label("Skin.String(iphone_remote_test)")))
        unf = await until(lambda: atv.keyboard.text_focus_state.name == "Unfocused")
        step("the dialog closed: the phone's keyboard goes", bool(unf), atv.keyboard.text_focus_state.name)
        step("no Enter after it (still Home, nothing opened)", kodi.window()["id"] == 10000, json.dumps(kodi.window()))
    finally:
        atv.close()

    phone = next(p for p in ctl.state["phones"] if p["name"] == "pyatv iPhone")
    await ctl.send({"cmd": "forget", "phone": phone["id"], "id": 1})
    await until(lambda: all(p["name"] != "pyatv iPhone" for p in ctl.state["phones"]))
    step("forgotten", all(p["name"] != "pyatv iPhone" for p in ctl.state["phones"]))


asyncio.run(main())
