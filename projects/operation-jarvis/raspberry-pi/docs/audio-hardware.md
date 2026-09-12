# Raspberry Pi Audio Hardware for Operation JARVIS

The room endpoint uses an Anker PowerConf for both microphone capture and speaker playback. These notes cover the recorded USB setup, Bluetooth limitations, and tests for diagnosing hardware trouble.

## Current deployed configuration

The documented setup uses USB audio at 48 kHz. The recovered/replacement hardware supports capture and playback at the same time, which lets a spoken `stop` interrupt JARVIS's response.

| Role | Current device/profile |
|---|---|
| Microphone | USB ALSA, `plughw:CARD=PowerConf,DEV=0`, 48 kHz mono capture |
| Speaker | USB ALSA, `plughw:CARD=PowerConf,DEV=0` |
| Listener | `jarvis-room-audio.service` running `/home/pi/jarvis-room-audio-client.py --vad-loop --interrupt-while-busy` |

The listener keeps USB capture running during acknowledgement and response playback. Idle turns need the local `hey_jarvis` wake word. While busy, short clips go to on-device Apple DictationTranscriber; only an exact normalized `stop` cancels generation and playback. Ordinary turns use on-device Apple SpeechTranscriber.

Bluetooth BlueALSA SCO/A2DP remains a fallback, but the PowerConf cannot reliably capture with SCO and play with A2DP at the same time. That rules out voice interruption on the Bluetooth path.

See [`../room_audio/README.md`](../room_audio/README.md) for the current server and listener commands.

## Long-term recommendation

Continue using the PowerConf as a **USB audio device**, preferably through a good powered USB hub if electrical instability returns.

Recommended hub characteristics:

- Externally powered.
- No unsafe backfeeding into the Pi.
- Stable with USB audio devices.
- Sufficient current budget for the PowerConf and any future peripherals.

USB avoids Bluetooth profile switching and supports the simultaneous input and output needed here.

## PowerConf hardware recommendation

Speakerphone options for this setup:

- **Primary pick:** Anker PowerConf **A3301**.
- **Close alternative:** Anker PowerConf **S3 / A3302** if prices are close.

Useful features for room audio:

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
