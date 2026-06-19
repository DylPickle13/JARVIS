#!/usr/bin/env bash
set -euo pipefail

# Anker PowerConf USB audio smoke test for Operation JARVIS.
# Run on the Raspberry Pi after connecting the PowerConf by USB-C -> USB-A.
# Optional overrides:
#   AUDIO_DEVICE=plughw:CARD,DEVICE ./test-anker-powerconf.sh
#   RECORD_SECONDS=5 SPEAKER_SECONDS=4 ./test-anker-powerconf.sh

RECORD_SECONDS="${RECORD_SECONDS:-5}"
SPEAKER_SECONDS="${SPEAKER_SECONDS:-3}"
TEST_WAV="${TEST_WAV:-/tmp/powerconf-test.wav}"
AUDIO_DEVICE="${AUDIO_DEVICE:-}"

section() {
  printf '\n== %s ==\n' "$1"
}

need_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing command: $1"
    return 1
  fi
}

section "identity"
hostname
whoami
date

section "required commands"
missing=0
for cmd in lsusb arecord aplay speaker-test timeout awk sed grep; do
  if need_cmd "$cmd"; then
    echo "ok: $cmd"
  else
    missing=1
  fi
done
if [[ "$missing" -ne 0 ]]; then
  cat <<'EOF'

Install the missing audio utilities, then rerun:
  sudo apt update
  sudo apt install -y alsa-utils usbutils
EOF
  exit 1
fi

section "usb devices"
lsusb || true

section "capture devices: arecord -l"
arecord -l || true

section "playback devices: aplay -l"
aplay -l || true

if [[ -z "$AUDIO_DEVICE" ]]; then
  # Prefer an obvious Anker/PowerConf/USB capture card. Falls back to the first capture card.
  card_device="$({ arecord -l | awk '
    BEGIN { IGNORECASE=1 }
    /^card / {
      line=$0
      card=$2; sub(":", "", card)
      dev="0"
      if (match(line, /device [0-9]+/)) {
        dev=substr(line, RSTART+7, RLENGTH-7)
      }
      if (line ~ /anker|powerconf|usb/) {
        print card "," dev
        found=1
        exit
      }
      if (first == "") first=card "," dev
    }
    END { if (!found && first != "") print first }
  '; } | tail -n 1)"
  if [[ -n "$card_device" ]]; then
    AUDIO_DEVICE="plughw:${card_device}"
  fi
fi

if [[ -z "$AUDIO_DEVICE" ]]; then
  cat <<'EOF'

No capture device was detected. Check that the PowerConf is connected by USB cable,
not Bluetooth, then rerun this script.
EOF
  exit 1
fi

section "selected ALSA device"
echo "$AUDIO_DEVICE"

section "speaker test"
echo "You should hear a short speaker-test voice from the PowerConf."
timeout "$SPEAKER_SECONDS" speaker-test -D "$AUDIO_DEVICE" -t wav -c 1 || true

section "microphone record"
echo "Speak a short phrase now. Recording ${RECORD_SECONDS}s to ${TEST_WAV}."
arecord -D "$AUDIO_DEVICE" -f cd -t wav -d "$RECORD_SECONDS" "$TEST_WAV"
ls -lh "$TEST_WAV"

section "microphone playback"
echo "Playing the recording back through ${AUDIO_DEVICE}."
aplay -D "$AUDIO_DEVICE" "$TEST_WAV"

section "done"
echo "PowerConf USB audio smoke test complete. If you heard both tests, JARVIS room audio hardware is ready."
