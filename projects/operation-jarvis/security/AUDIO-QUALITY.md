# Camera audio quality: verified paths, not advertised assumptions

## Current choice

- JARVIS TTS: existing high-quality cached Piper model/preferences.
- Camera **microphone**: native **PCMU (G.711 mu-law), mono 16 kHz**, without an
  intermediate downsample to 8 kHz. The camera room endpoint opts into the patch
  described below. The local wake/ASR client already consumes 16 kHz PCM.
- Camera **speaker**: physically accepted **PCMA (G.711 A-law), mono 8 kHz**.
  Both standalone CLI and room replies keep this proven path.

This is the best validated combination in this integration, not a claim that
16 kHz speaker playback is impossible with every implementation/firmware.

## Why the rates differ

A bounded, read-only query of the commissioned C230 returned:

- Speaker: G711ulaw / G711alaw, advertised rates 16 and 8 kHz, mono.
- Microphone: G711ulaw, 16 kHz, mono.

The microphone's live configuration also reports 16 kHz G711ulaw. Stock go2rtc
v1.9.14 receives that native microphone stream but transcodes it to PCMA/8000.
The previous client then resampled it back to 16 kHz: that could not restore the
lost detail.

**Speaker experiments were rejected.** Sending PCMU/16000 with MPEG-TS type 0x91
and 90 kHz PTS, then also testing an explicit talk-session audio_config request,
produced subjectively slowed playback in both owner listening tests. API success
and advertised capabilities did not prove correct playback. Neither experiment
was installed as the active endpoint. Do not compensate by speeding up source
speech and call that higher quality. Proper 16 kHz talkback negotiation/timing is
still unresolved. No persistent camera audio configuration was changed.

## Minimal microphone-only go2rtc patch

`go2rtc-microphone16.patch` applies to upstream **AlexxIT/go2rtc v1.9.14**:

1. Opt in with the `audio=mic16` URL query parameter (append `?audio=mic16`
   when the Tapo URL has no existing query).
2. Advertise the microphone as PCMU/16000 with dynamic RTP payload type 96.
3. Route the camera's native 0x91 microphone packets without the stock 16-to-8 kHz
   transcode; retain the existing MPEG-TS-to-RTP timestamp conversion.
4. Leave the speaker codec PCMA/8000 and all talkback/muxer code unchanged.

The final patched `pkg/tapo/backchannel.go` and `pkg/mpegts/muxer.go` were checked
byte-for-byte against the upstream release and are identical. A Go unit test
asserts the microphone opt-in cannot change the speaker's advertised codec/rate.
Without the query option, stock behavior is retained. This opt-in is for a camera
whose actual native microphone format has been checked, not all Tapo models.

Build from a clean reviewed v1.9.14 source tree:

```sh
patch -p1 < /path/to/security/go2rtc-microphone16.patch
go test ./pkg/tapo
go build -trimpath -o go2rtc .
```

The local build used an official SHA256-verified Go 1.27.1 darwin-arm64 archive,
installed only inside the ignored private experiment directory. The resulting
app is separately named **JARVIS Camera Audio 16k**, with a Local Network usage
description and owner-approved macOS permission. Despite its name, “16k” applies
**only to microphone capture**. The original release app remains available for
rollback. Source archives, Go toolchain/cache, app binaries, private capability
reports and temporary audio are not published.

## Integration and checks

`CameraSession(..., microphone16=True)` requires the patched app and verifies
PCMU/16000 input plus PCMA/8000 output capabilities before use. The room supervisor
uses its private `microphone16` boolean to select the app; new provisioning can
opt in with `--native-microphone16`. The standalone CLI remains on the proven
original speaker path and does not enable an experimental speaker format.

A live mixed-rate test delivered microphone PCM throughout a silent speaker
reply, detected reply EOF normally, and cancelled another reply in about 83 ms.
The active room endpoint subsequently reported microphone=16000 Hz, speaker=8000
Hz, local wake model online, and an online/idle heartbeat. Human wake/recognition
performance at room distance should still be checked; transport metrics are not
an intelligibility or echo-cancellation measurement.

For rollback, set the camera endpoint's private `microphone16` value to false and
restart only `com.operation-jarvis.room-audio-camera`. This restores stock microphone
transcoding without returning to Raspberry Pi hardware. Keep its owner-only
`environment.before-mic16.json` backup private.
