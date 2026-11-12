#!/bin/sh
# SPDX-License-Identifier: GPL-2.0-only
#
# prepare-profile.sh: bring a fresh LibreELEC bench profile (/storage) into
# the state every benchmark image is measured in, and print that state as
# "key=value" lines. Runs on the box (busybox sh). Safe to run again.
#
# What it sets, and nothing else:
#  - LibreELEC's first-run wizard closed (oe_settings.xml wizard_completed);
#  - Kodi's web server on, user kodi, password bench (JSON-RPC on port 8080);
#  - audio passthrough on, every format, audio device = passthrough device =
#    the HDMI ALSA device with a sink (BENCH_AUDIO_DEVICE overrides);
#  - "adjust display refresh rate" on start/stop;
#  - DVBRIDGE_DIAGNOSTICS=1 in /storage/.config/native-dv.env, so every image
#    writes Kodi's own drop/skip counters ("DVBridge playback health") to the
#    log every 10 s. 0.4 does that by default; 0.5 only when asked.
# The Dolby Vision settings and the GUI resolution stay as the image has them.
#
# Kodi is restarted once (wizard, web server, environment), only if nothing is
# playing.

set -u

RPC_HTTP="http://127.0.0.1:8080/jsonrpc"
RPC_USER="kodi:bench"
GUISETTINGS="/storage/.kodi/userdata/guisettings.xml"
OE_DIR="/storage/.kodi/userdata/addon_data/service.libreelec.settings"
OE_FILE="${OE_DIR}/oe_settings.xml"
ENV_FILE="/storage/.config/native-dv.env"
IDLE='{"id":1,"jsonrpc":"2.0","result":[]}'
PING='{"jsonrpc":"2.0","method":"JSONRPC.Ping","id":1}'
PLAYERS='{"jsonrpc":"2.0","method":"Player.GetActivePlayers","id":1}'

die() {
  echo "prepare-profile: $*" >&2
  exit 1
}

http() {
  curl -s -m 10 -u "${RPC_USER}" -H 'Content-Type: application/json' -d "$1" "${RPC_HTTP}"
}

# Kodi's localhost TCP port: on in a fresh profile, before the web server is.
tcp() {
  printf '%s' "$1" | nc -w 3 127.0.0.1 9090
}

call() {
  http "{\"jsonrpc\":\"2.0\",\"method\":\"$1\",\"params\":$2,\"id\":1}"
}

set_value() {
  call Settings.SetSettingValue "{\"setting\":\"$1\",\"value\":$2}" | grep -q '"result":true' ||
    die "could not set $1 to $2"
}

# A passthrough format's setting exists for JSON-RPC only once Kodi's audio
# engine has opened the passthrough device and knows what it takes: some
# seconds after Kodi's start or a change of device.
set_value_wait() {
  n=0
  until call Settings.SetSettingValue "{\"setting\":\"$1\",\"value\":$2}" |
    grep -q '"result":true'; do
    n=$((n + 1))
    [ "${n}" -lt 30 ] || die "could not set $1 to $2 in 60 s"
    sleep 2
  done
}

get_value() {
  call Settings.GetSettingValue "{\"setting\":\"$1\"}" |
    sed -n 's/.*"value":"\{0,1\}\([^"}]*\)"\{0,1\}}.*/\1/p'
}

# guisettings.xml, while Kodi is stopped: Kodi asks on screen before it turns
# the web server on over JSON-RPC, and that dialog blocks JSON-RPC.
set_xml() {
  sed -i -e "s|<setting id=\"$1\"[^>]*>[^<]*</setting>|<setting id=\"$1\">$2</setting>|" \
    -e "s|<setting id=\"$1\"[^>]*/>|<setting id=\"$1\">$2</setting>|" "${GUISETTINGS}"
  grep -q "<setting id=\"$1\">$2</setting>" "${GUISETTINGS}" || die "guisettings.xml: no $1"
}

wait_kodi() {
  n=0
  until "$1" "${PING}" | grep -q pong; do
    n=$((n + 1))
    [ "${n}" -lt 60 ] || die "Kodi's JSON-RPC ($1) did not answer in 120 s"
    sleep 2
  done
}

wizard_closed() {
  grep -q '<wizard_completed>True</wizard_completed>' "${OE_FILE}" 2>/dev/null
}

diagnostics_on() {
  grep -q '^DVBRIDGE_DIAGNOSTICS=1$' "${ENV_FILE}" 2>/dev/null
}

if systemctl -q is-active kodi; then
  rpc=tcp
  http "${PING}" | grep -q pong && rpc=http
  wait_kodi "${rpc}"
  [ "$("${rpc}" "${PLAYERS}")" = "${IDLE}" ] || die "something is playing: not touching Kodi"
else
  rpc=none
fi

if [ "${rpc}" != http ] || ! wizard_closed || ! diagnostics_on; then
  systemctl stop kodi
  if ! wizard_closed; then
    [ -s "${OE_FILE}" ] && die "${OE_FILE} exists without wizard_completed: not a fresh profile"
    mkdir -p "${OE_DIR}"
    printf '%s\n' '<?xml version="1.0" ?>' '<libreelec>' '	<addon_config/>' '	<settings>' \
      '		<libreelec>' '			<wizard_completed>True</wizard_completed>' \
      '		</libreelec>' '	</settings>' '</libreelec>' > "${OE_FILE}"
  fi
  diagnostics_on || echo 'DVBRIDGE_DIAGNOSTICS=1' >> "${ENV_FILE}"
  set_xml services.webserver true
  set_xml services.webserverauthentication true
  set_xml services.webserverusername "${RPC_USER%%:*}"
  set_xml services.webserverpassword "${RPC_USER#*:}"
  systemctl start kodi
  sleep 5
  wait_kodi http
  sleep 10
fi

set_value videoplayer.adjustrefreshrate 2

# The HDMI device Kodi labels with a sink's name ("..., DENON-AVR on HDMI #0").
# The list is complete once the audio engine has enumerated its devices.
hdmi_device() {
  call Settings.GetSettings \
      '{"filter":{"section":"system","category":"audio"},"level":"expert"}' |
    sed 's/.*"id":"audiooutput.passthroughdevice"//; s/\].*//' | tr '{' '\n' |
    sed -n 's/.*"label":"[^"]*, [^"]* on HDMI #[0-9]*","value":"\(ALSA:hdmi:[^"]*\)".*/\1/p' |
    head -n 1
}
device="${BENCH_AUDIO_DEVICE:-}"
n=0
while [ -z "${device}" ] && [ "${n}" -lt 30 ]; do
  device=$(hdmi_device)
  [ -n "${device}" ] || sleep 2
  n=$((n + 1))
done
[ -n "${device}" ] || die "no HDMI ALSA device with a sink; set BENCH_AUDIO_DEVICE"
set_value audiooutput.passthrough true
set_value audiooutput.audiodevice "\"${device}\""
set_value audiooutput.passthroughdevice "\"${device}\""
for s in ac3passthrough eac3passthrough dtspassthrough truehdpassthrough dtshdpassthrough; do
  set_value_wait "audiooutput.${s}" true
done

window=$(call GUI.GetProperties '{"properties":["currentwindow"]}' |
  sed -n 's/.*"currentwindow":{"id":\([0-9]*\).*/\1/p')
[ "${window}" = 10000 ] || die "Kodi is not on the home screen (window ${window}): wizard open?"

echo "window=${window}"
for s in services.webserver videoplayer.adjustrefreshrate audiooutput.passthrough \
         audiooutput.audiodevice audiooutput.passthroughdevice audiooutput.truehdpassthrough \
         audiooutput.eac3passthrough audiooutput.dtshdpassthrough audiooutput.channels \
         videoscreen.resolution videoscreen.screenmode videoscreen.limitguisize \
         videoscreen.whitelist videoscreen.noofbuffers videoplayer.usedisplayasclock \
         videoplayer.usevaapi videoplayer.prefervaapirender locale.subtitlelanguage \
         dvbridge.outputmode dvbridge.hdr10plussources dvbridge.elupscaler \
         dvbridge.dvmetadata dvbridge.tvpeak dvbridge.removel2 dvbridge.enhancedinfo \
         dvbridge.menumode dvbridge.guicache dvbridge.homecache dvbridge.halfgui \
         dvbridge.verify dvbridge.frametrace dvbridge.gputiming lookandfeel.skin; do
  echo "${s}=$(get_value "${s}")"
done
echo "native-dv.env.override=$(tr '\n' ' ' < "${ENV_FILE}")"
echo "wizard_completed=True"
