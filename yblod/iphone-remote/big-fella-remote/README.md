# big-fella-remote

The TV box in the **iPhone's own TV remote** (Control Center's Remote
button, the lock screen, the Action button, the "Apple TV Remote" app),
with **nothing to install on the phone**. A small Rust system service that
speaks Apple's *Companion Link* protocol and says it's an Apple TV: the
iPhone lists the box, pairs with a 4-digit PIN the TV shows, and sends its
buttons, touch-area swipes, volume buttons and keyboard text.

Why and how this works, and what else was considered:
[docs/research/ios-remote.md](../docs/research/ios-remote.md). It sits
next to [big-fella-connect](../big-fella-connect/) (KDE Connect, Android
and iOS, touchpad and media info), not instead of it.

- **Finding it**: announced over mDNS as `_companion-link._tcp` (the
  daemon answers mDNS itself: there's no Avahi on the box), with an Apple
  TV's TXT record. The name the phone lists is the host name, or `name` in
  `/etc/big-fella/remote.toml`.
- **Pairing**, once per iPhone: pick the box in the remote; the TV shows
  *Pair an iPhone* with a PIN; type it on the phone. A new random PIN each
  time, on screen two minutes at most; Back or OK on the TV cancels. After
  a wrong PIN the next try waits 3 s. Settings > Phones lists the paired
  iPhones (forget them there) and turns pairing of new ones on or off.
- **Reconnecting** needs nothing: the phone proves it's the one that paired
  (pair-verify, against its key kept in `/var/lib/big-fella-remote`).
- **Buttons** as the keys the LG remote's remote-bridged sends, so the shell
  and the apps need nothing new: Back (Menu) → Esc, Select and a tap → Enter,
  TV (Home) → Home (`home_key`, 172), Play/Pause → Play/Pause, ±10 s →
  fast forward / rewind (the player's seek), Channel/Page ± → Page Up/Down,
  Guide → EPG. A held button is a held key (KWin repeats it), and a key
  still down when the phone goes is let up.
- **Swipes** on the touch area as arrows, the way tvOS moves its focus (the
  iOS 27 remote has no D-pad): one arrow per 160/1000 of travel while the
  finger moves, so a long swipe walks several tiles; a finger resting near
  the edge it moved towards repeats the arrow (long lists); a short touch
  is OK. `[touch]` in the config tunes it.
- **Volume**: the iPhone's own volume buttons (the remote advertises volume
  control) go to **speakerd** while it's up and has its speaker, as the LG
  remote's do through remote-bridged; otherwise they're the volume keys,
  which the shell sends to PipeWire. Held, a step every 150 ms.
- **The phone's keyboard**: when a text field in the shell has the focus
  (search, a prompt), the phone raises its keyboard by itself ("Apple TV
  Keyboard"), showing the field's text; what's typed goes into the field,
  any language and emoji; Return is Enter. Away from the field, the phone's
  keyboard goes.

Not: Siri (the button arrives, the voice doesn't: unsolved by anyone), what's
playing in the remote, launching apps, power. No AirPlay is advertised.

## Layout

| file | role |
|---|---|
| `src/frame.rs` | frames: type, 3-byte length, payload; sealed E_OPACK frames |
| `src/opack.rs` | OPACK, Apple's binary serialisation, both ways (with Apple's reference table) |
| `src/tlv8.rs` | TLV8, HomeKit's pairing records |
| `src/srp.rs` | SRP-6a, 3072-bit group, SHA-512 (both sides) |
| `src/crypto.rs` | HKDF-SHA512, ChaCha20-Poly1305 with label nonces and per-direction counters |
| `src/pairing.rs` | pair-setup and pair-verify (both sides: the phone's for tests) |
| `src/session.rs` | a verified phone's messages: answers and effects (keys, volume, text) |
| `src/touch.rs` | the touch area as arrows and taps |
| `src/keys.rs` | buttons and media commands to key codes (remote-bridged's) |
| `src/rti.rs` | the keyboard's NSKeyedArchiver payloads (`_tiStarted`, `_tiC`) |
| `src/advertise.rs` | the mDNS service and the `_systemInfo` answer |
| `src/conn.rs` | one phone's connection |
| `src/daemon.rs` | the event loop: connections, pairing, keys, speaker, home screen |
| `src/control.rs` | the control socket the home screen uses |
| `src/speaker.rs` | speakerd's socket (the user's, checked) |
| `src/store.rs` | `/var/lib/big-fella-remote`: our identity and key, paired iPhones, the pairing setting |
| `src/uinput.rs` | the virtual keyboard, "big-fella iPhone remote" |
| `src/tests.rs` | the daemon end to end, a phone in Rust against the control socket |
| `tests/e2e/` | pyatv as the iPhone against the real binary on Linux (Docker, uinput, mDNS) |
| `packaging/` | systemd unit, uinput module load, example config; `arch/PKGBUILD` |

The home screen's side is in `big-fella-shell`: `services/Remote.qml` (the
socket, offering the focused field, applying the phone's typing),
`RemotePrompt.qml` (the PIN) and `components/settings/PhonesPage.qml`
(the paired iPhones).

## The protocol

Undocumented and reverse-engineered; this is written from:

- **pyatv's documentation** ([pyatv.dev, Protocols](https://pyatv.dev/documentation/protocols/),
  MIT): frames, OPACK, the pairing, the HID codes, the media commands.
  pyatv's client side is also what the tests use as the iPhone.
- **atv-core** ([corvofeng/atv-core](https://github.com/corvofeng/atv-core),
  a Rust "Fake Apple TV"): facts only (its Cargo.toml says MIT, but there's
  no LICENSE file, so none of its code is used): iOS 27's `_systemInfo`
  quirk, swipes as directions, how SRP's numbers are hashed.
- **windows-apple-remote** ([aryakvn/windows-apple-remote](https://github.com/aryakvn/windows-apple-remote),
  MIT): the `_systemInfo` answer and TXT values iOS 27 accepts, "answer
  everything", Apple's OPACK reference table, a tap as Select.
- **CompanionGames** ([thiccaxe/CompanionGames](https://github.com/thiccaxe/CompanionGames),
  AGPL-3.0): facts only, no code: the server-started keyboard
  (`_tiStarted` and its archive's shape), iOS 18's transient pairing.
- HomeKit's pairing as the HAP specification describes it (SRP, Ed25519,
  X25519, HKDF, ChaCha20-Poly1305).

All of the code here is our own (Apache-2.0).

In short:

1. **mDNS**: `_companion-link._tcp`, TXT `rpMd=AppleTV5,3`, `rpVr=715.2`,
   `rpFl=0xB6782` (these gate what the remote shows, the volume buttons
   among them), and `rpHN/rpHA/rpAD/rpHI/rpBA/rpMac/rpMRtID`, stable ones
   derived from our key (a real Apple TV rotates them).
2. **Frames**: a type byte (3/4 pair-setup, 5/6 pair-verify, 8 E_OPACK), a
   3-byte big-endian length, the payload: an OPACK dictionary, its `_pd` a
   TLV8 record while pairing.
3. **Pair-setup** (HomeKit's): M1 → the PIN on the screen, M2 salt and B;
   M3/M4 the SRP proofs (wrong PIN: error 2); M5/M6 the long-term Ed25519
   keys and identifiers, sealed, signed over HKDF-derived values. A
   transient pair-setup (iOS 18's fallback) is hung up on.
4. **Pair-verify**, every connection: X25519, each side signs both
   ephemeral keys with its long-term key; we check the phone's against the
   key it paired with (error 2 otherwise, and the phone pairs). Then
   `ServerEncrypt-main` / `ClientEncrypt-main` keys, a 12-byte counter
   nonce per direction, the frame header as associated data.
5. **Session**: `{"_i", "_t", "_x", "_c"}` messages; every one is answered.
   `_systemInfo`, `_sessionStart`, `TVRCSessionStart`, `_touchStart`,
   `_interest`/`FetchMediaControlStatus` (media flags: play, pause, skip,
   volume), `FetchAttentionState`, `_hidC` (buttons), `_hidT` (touch),
   `_mcc` (media and volume), `_tiStart`/`_tiC` (keyboard); we send
   `_iMC`, `_tiStarted` and `_tiStopped`.

## The keyboard: why the shell, not uinput

The phone's typing reaches the field **through the control socket**: the
daemon passes the phone's edits (`replace`, `delete`, `insert`) to
`services/Remote.qml`, which writes them into `Osk.field` (the field the
on-screen keyboard is for). Not as key presses through uinput, as
big-fella-connect types, because:

- **Unicode**: uinput types keys of the US layout, so only ASCII (connect's
  `us_key`); the phone sends any text (é, ü, emoji, CJK).
- **plasma-keyboard**: while a field has the input method active, the
  on-screen keyboard grabs the keys (services/Osk.qml), and its D-pad ring
  takes arrows and Enter; injected letters would go through it.
- **Whole-text edits**: the phone also sends "the text is now X"
  (`textToAssert`), which as keys would be select-all, delete, retype.
- **Read back**: the shell sends the field's text back, so the phone shows
  what's really in the field (and pyatv's `text_get` in the tests reads it).

KWin's input method (input-method-v2) would take Unicode too, but it's
plasma-keyboard's: KWin has one input method, and another client can't
commit text through it. The only key that goes through uinput is the
phone's Return, as Enter, 150 ms after the text before it (so they can't
cross), which the fields already take as "done".

Only the shell's own fields get the phone's keyboard: a field in another
app (Firefox) doesn't tell the shell it has the focus. KWin's
`org.kde.kwin.VirtualKeyboard` (`activeClientSupportsTextInput`) could say
so; typing there would need EIS (libei) in the session, as connect's README
says under Unicode. Not done.

Passwords: a password field's text isn't sent to the phone (it shows an
empty field), but what's typed on the phone's keyboard is on its screen.

## Security

- **Only paired iPhones do anything.** Before pair-verify only pairing
  frames are read; anything else hangs up. Every pairing needs the PIN
  shown on the TV; Settings > Phones can turn pairing of new iPhones off
  (then pair-setup is refused, error 6). One pairing at a time (another
  address: busy).
- **Checked identities**: pair-verify checks the phone's signature against
  the key it paired with (pyatv's own test server doesn't). A forgotten
  phone is hung up on at once and refused after.
- **LAN only**: connections from addresses that aren't loopback, private,
  link-local, CGNAT or unique local are refused; the unit's IP filter
  allows only those (and mDNS's multicast). big-fella-settings' firewall
  opens TCP 49153 to private IPv4 addresses only (`iphone_from`).
- **Bounded**: 8 KB frames before verify, 256 KB after; 4 connections per
  address, 16 in all; 30 s to verify (2 minutes while a PIN is up); text
  4096 characters per edit; OPACK nested 32 deep at most. Nothing panics on
  what the network sends (`cargo test` runs random bytes through OPACK and
  TLV8).
- **The control socket** (`/run/big-fella-remote/control.sock`) checks its
  peer's uid: root and people's accounts (1000-59999, or `control_uids`).
  At most 8 clients, 64 KB lines. It never carries the keys; the PIN only
  while it's on the screen.
- **speakerd's socket** is connected to only if it's a socket its
  /run/user/UID folder's owner made and that user's process serves
  (remote-bridged's rules).
- **The unit**: as big-fella-connect's: root without capabilities (for
  `/dev/uinput`), `DeviceAllow=/dev/uinput` only, `ProtectSystem=strict`,
  `@system-service` syscalls without `@privileged`/`@resources`,
  AF_INET/AF_INET6/AF_UNIX/AF_NETLINK (the interfaces' addresses, for
  mDNS), `MemoryDenyWriteExecute`, 128 MB and 16 tasks at most. It writes
  only `/var/lib/big-fella-remote` (0700, files 0600) and
  `/run/big-fella-remote`.

## Build and test

```sh
cargo test            # 38 tests: OPACK (random bytes, round trips, references),
                      # TLV8, SRP, both sides of pairing, the session, the touch
                      # area, the archives, and the daemon end to end with a
                      # phone in Rust (pair, verify, buttons, swipes, volume,
                      # typing, forget, refusals) and a fake home screen
tests/e2e/docker.sh   # Linux, Docker: the release binary with uinput and mDNS,
                      # pyatv as the iPhone (found by mDNS, paired with the PIN
                      # off the control socket, verified, buttons, swipes,
                      # volume, typing), evtest on the virtual keyboard
```

`tests/e2e/fake_iphone.py HOST PORT CONTROL_SOCKET [--scan]` runs on its
own too (it needs pyatv 0.18 with srptools 1.0.1: `pip install pyatv
srptools==1.0.1` in a venv; srptools 2 broke pyatv's pairing), on the box
itself as root (the control socket): it pairs, so it adds a phone; it
forgets it at the end. Installed as `/usr/lib/big-fella-remote/fake-iphone`.

## Install

On Arch, `makepkg -si` in `packaging/arch`, then:

```sh
systemctl enable --now big-fella-remote
```

The package alone leaves it off; the `big-fella` meta package (0.1.0-14)
turns it on (its preset on install, and on the upgrade to it), as it does
big-fella-connect. It's a system service (multi-user.target), not the
session's: uinput is root's, and the part that parses the network runs
with no access to the user's files. The shell finds its socket by itself
(Settings > Phones shows the iPhones part while it runs).

`/etc/big-fella/remote.toml` (optional) sets the name the iPhone lists, the
first-run pairing default, the port (49153), the Home key, the touch
tuning and speakerd (`packaging/remote.toml`). Change the port and the
firewall's rule goes with it (`/etc/big-fella/firewall.nft`).

### Pairing an iPhone

1. The iPhone on the TV's network. Control Center → the Remote button (add
   it in Settings → Control Center if it isn't there).
2. Tap the device name at the top, pick the box (its host name).
3. The TV shows *Pair an iPhone* and four digits; type them on the phone.
4. Swipe on the touch area to move, tap for OK; the buttons below are Back
   and TV (Home); the phone's volume buttons are the speaker's.

## The control socket

`/run/big-fella-remote/control.sock`, one JSON object per line each way.

From the service: `{"state": {"name", "pairing", "keyboard", "remotes",
"phones": [{"id", "name", "model", "paired_at", "connected", "address"}],
"request": null or {"pin", "address", "seconds"}}}` on connect and every
change; `{"event": "paired", "phone": {"id", "name"}}`; `{"event": "text",
"replace": null or "...", "delete": N, "insert": "..."}` (the phone's
typing, for the focused field: replace first, then delete before the
cursor, then insert); `{"error", "cmd", "id"}`, and `{"ok": true, "cmd",
"id"}` for a command that had an `id`.

To the service: `{"cmd": "pairing", "value": true}`, `{"cmd": "forget",
"phone": "<id>"}`, `{"cmd": "cancel"}` (the PIN on screen),
`{"cmd": "keyboard", "open": true, "field": N, "text": "...", "title":
"..."}` (a field has the focus: a new `field` number is a new typing
session on the phone, the same one just new text) or `{"cmd": "keyboard",
"open": false}`, `{"cmd": "state"}`.

## Not yet

- **Tested on a real iPhone**: so far only against pyatv (the protocol's
  client side) and the daemon's own tests
  ([docs/evidence/ios-remote-2026-11-03.md](../docs/evidence/ios-remote-2026-11-03.md),
  with the steps for a real one). The research's sources are iPhones on
  iOS 17, 18 and 27.
- Swipe tuning on the real shell (step, edge repeat), and velocity for
  fast lists.
- The phone's keyboard for other apps' fields (above).
- Media state in the remote (play/pause showing what's playing), Siri.
