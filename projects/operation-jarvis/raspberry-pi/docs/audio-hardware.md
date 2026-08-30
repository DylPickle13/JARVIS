# Raspberry Pi Audio Hardware for Operation JARVIS

This note tracks the Anker PowerConf room-audio hardware used by the Raspberry Pi endpoint.

## Current deployed configuration

The active room endpoint uses the Anker PowerConf over USB at 48 kHz. The recovered/replacement hardware path supports simultaneous microphone capture and speaker playback, which is required for voice barge-in.

| Role | Current device/profile |
|---|---|
| Microphone | USB ALSA, `plughw:CARD=PowerConf,DEV=0`, 48 kHz mono capture |
| Speaker | USB ALSA, `plughw:CARD=PowerConf,DEV=0` |
| Listener | `jarvis-room-audio.service` running `/home/pi/jarvis-room-audio-client.py --vad-loop --interrupt-while-busy` |

The boot-time listener keeps USB capture running while the processing acknowledgement and final response play. Idle commands still require local `hey_jarvis`; while a turn is busy, short speech clips are sent to on-device Apple DictationTranscriber, and only an exact normalized `stop` transcript cancels generation/playback. Ordinary turns use on-device Apple SpeechTranscriber. Bluetooth BlueALSA SCO/A2DP remains a fallback transport, but it cannot support barge-in because the PowerConf does not reliably hold SCO capture and A2DP playback simultaneously.

See [`../room_audio/README.md`](../room_audio/README.md) for the current server and listener commands.

## Long-term recommendation

Continue using the PowerConf as a **USB audio device**, preferably through a good powered USB hub if electrical instability returns.

Recommended hub characteristics:

- Externally powered.
- No unsafe backfeeding into the Pi.
- Stable with USB audio devices.
- Sufficient current budget for the PowerConf and any future peripherals.

USB is still preferable long-term because it provides simultaneous mic input and speaker output without Bluetooth profile switching.

## PowerConf hardware recommendation

Recommended budget “buy once” speakerphone:

- **Primary pick:** Anker PowerConf **A3301**.
- **Close alternative:** Anker PowerConf **S3 / A3302** if prices are close.

Why it fits JARVIS:

- 6-mic 360° room pickup.
- Echo cancellation / noise reduction.
- Full-duplex speakerphone design.
- Speaker is good enough for JARVIS voice, podcasts, and casual music.
- Standard USB audio behavior on Linux when power is stable.

This is a conference speakerphone, not hi-fi. For better music later, keep the PowerConf as the microphone/speakerphone and add a larger powered speaker separately.

## USB findings from 2026-05-21

The Pi detected the PowerConf over USB:

```text
291a:3301 Anker PowerConf
card 2: PowerConf [PowerConf], device 0: USB Audio
```

However, one physical USB path repeatedly produced:

```text
usb 1-1-port2: over-current change
Cannot get card index for PowerConf
arecord: audio open error: No such device
```

A different USB socket was more stable during testing and passed:

- 48 kHz stereo playback.
- 48 kHz mono microphone recording.
- 15-second full-duplex playback + recording.

The conclusion is that the software path works, but the remaining USB issue is likely physical/electrical stability. Prefer a powered hub before returning to wired USB permanently.

## Detection and test commands

After plugging the PowerConf into the Pi by USB:

```bash
lsusb
arecord -l
aplay -l
```

Run the repository smoke test from this JARVIS environment:

```bash
ssh -i ~/.ssh/jarvis_dashboard_host -o IdentitiesOnly=yes pi@<private-lan-ip> \
  'bash -s' < projects/operation-jarvis/raspberry-pi/scripts/test-anker-powerconf.sh
```

Or copy and run `scripts/test-anker-powerconf.sh` directly on the Pi.

Basic speaker test:

```bash
speaker-test -t wav
```

Basic microphone test, replacing `CARD`/`DEVICE` with values from `arecord -l`:

```bash
arecord -D plughw:CARD,DEVICE -f cd -t wav /tmp/powerconf-test.wav
aplay /tmp/powerconf-test.wav
```
