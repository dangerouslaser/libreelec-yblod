# YBLOD's iPhone remote settings: pairing on or off, the paired iPhones, the
# service on or off. Talks to big-fella-remote's control socket (JSON lines).
import json
import os
import socket
import subprocess
import time

import xbmcgui

SOCKET = "/run/iphone-remote/control.sock"
DISABLED = "/storage/.cache/services/iphone-remote.disabled"
TITLE = "iPhone Remote"
UNITS = ["iphone-remote.service", "iphone-remote-kodi.service"]


class Control:
    def __init__(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(3)
        self.sock.connect(SOCKET)
        self.buf = b""
        self.next_id = 0

    def lines(self):
        while True:
            while b"\n" in self.buf:
                line, self.buf = self.buf.split(b"\n", 1)
                try:
                    yield json.loads(line)
                except ValueError:
                    pass
            data = self.sock.recv(65536)
            if not data:
                return
            self.buf += data

    def state(self):
        for msg in self.lines():
            if "state" in msg:
                return msg["state"]
        raise IOError("no state")

    def command(self, cmd, **args):
        self.next_id += 1
        args.update({"cmd": cmd, "id": self.next_id})
        self.sock.sendall((json.dumps(args) + "\n").encode())
        for msg in self.lines():
            if msg.get("id") == self.next_id:
                if "error" in msg:
                    raise IOError(msg["error"])
                return

    def close(self):
        self.sock.close()


def systemctl(*args):
    subprocess.call(["systemctl"] + list(args))


def turn(on):
    if on:
        if os.path.exists(DISABLED):
            os.remove(DISABLED)
        systemctl("start", *UNITS)
    else:
        os.makedirs(os.path.dirname(DISABLED), exist_ok=True)
        open(DISABLED, "w").close()
        systemctl("stop", *UNITS)


def connect():
    for _ in range(10):
        try:
            return Control()
        except OSError:
            time.sleep(0.5)
    return None


def main():
    dialog = xbmcgui.Dialog()
    while True:
        if os.path.exists(DISABLED):
            if dialog.yesno(TITLE, "The iPhone remote is off. Turn it on?"):
                turn(True)
                continue
            return
        ctl = connect()
        if ctl is None:
            dialog.ok(TITLE, "The iPhone remote isn't running.")
            return
        try:
            state = ctl.state()
            phones = state.get("phones", [])
            items = ["Allow new iPhones to pair: %s" % ("on" if state.get("pairing") else "off")]
            for p in phones:
                items.append("Forget %s%s" % (p.get("name") or "iPhone",
                                              " (connected)" if p.get("connected") else ""))
            items.append("Turn the iPhone remote off")
            heading = "%s: \"%s\", %d paired" % (TITLE, state.get("name", ""), len(phones))
            choice = dialog.select(heading, items)
            if choice < 0:
                return
            if choice == 0:
                ctl.command("pairing", value=not state.get("pairing"))
            elif choice == len(items) - 1:
                if dialog.yesno(TITLE, "Turn the iPhone remote off? iPhones won't find this box."):
                    ctl.close()
                    turn(False)
                    return
            else:
                p = phones[choice - 1]
                if dialog.yesno(TITLE, "Forget %s? It has to pair again." % (p.get("name") or "this iPhone")):
                    ctl.command("forget", phone=p["id"])
        except (OSError, IOError) as e:
            dialog.ok(TITLE, "The iPhone remote didn't answer (%s)." % e)
            return
        finally:
            ctl.close()


main()
