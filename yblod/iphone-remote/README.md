# iPhone remote

The box in the iPhone's own TV remote (Control Center, the lock screen, the
Apple TV Remote app), with nothing to install on the phone. Pick the box on
the iPhone, type the PIN Kodi shows, and the phone's buttons, swipes, volume
buttons and keyboard work in Kodi.

- `big-fella-remote/` and `bf-daemon/`: big-fella's crates (Apache-2.0),
  vendored unchanged from dangerouslaser/big-fella (the commit is in the
  commit that last updated them). How the protocol works:
  `big-fella-remote/README.md`. The daemon speaks Apple's Companion Link
  protocol and types on a uinput keyboard; `big-fella-remote-kodi` (in the
  same crate, `src/kodi.rs`) is Kodi's side: the PIN as a Kodi notification,
  and the phone's keyboard for Kodi's keyboard dialog, over JSON-RPC.
- `libreelec/`: this image's side.
  - `iphone-remote.service` runs the daemon with `remote.toml.in`, or with
    `/storage/.config/iphone-remote.toml` if there is one. Paired iPhones
    and the box's key are kept in `/storage/.cache/iphone-remote`.
  - `iphone-remote-kodi.service` runs the Kodi side (JSON-RPC on
    127.0.0.1:9090).
  - `script.yblod.iphoneremote`: Programs > iPhone Remote turns pairing of
    new iPhones on or off, forgets paired ones, and turns the remote off
    (`/storage/.cache/services/iphone-remote.disabled`).

On LibreELEC, Avahi answers mDNS for the host name, so the daemon announces
its service under its own name (`<host>-iphone-remote.local`). The home
firewall profile already accepts TCP 49153 from private addresses.

Keys in Kodi: Back is Esc (PreviousMenu), Select and a tap are Enter
(Select), TV is Home, Play/Pause, the ±10 s buttons are Kodi's fast forward
and rewind, Channel ± are Page Up/Down, volume is Kodi's volume keys.
