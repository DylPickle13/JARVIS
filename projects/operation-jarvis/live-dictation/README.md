# Live Pi dictation

Live local-network dictation from the Mac mini's USB PowerConf microphone into Pi.

## Runtime flow

1. VS Code forwards `F1` to Pi as `ESC O P` (`\u001bOP`).
2. `.pi/extensions/61-live-dictation.ts` starts FFmpeg capture from `PowerConf` as 16 kHz mono PCM.
3. While recording, the extension sends rolling WAV snapshots to the existing `whisper-large-v3-turbo-asr-4bit` model on the `mac-mini-16` oMLX server.
4. Pi replaces the provisional editor transcript as Whisper refines it.
5. A deliberate second `F1` stops capture, requests the final transcript, and leaves it in the editor without submitting.

The implementation does not use Apple Dictation, Apple Shortcuts, the clipboard, Accessibility automation, or a model installed on `mac-mini-64`.

## Use

Press `F1`, speak, and watch the provisional transcript update. Press `F1` again to stop and finalize. Avoid typing in the Pi editor during active dictation because live updates replace the provisional editor contents.

The oMLX model is loaded on demand; the integration does not pin it.

## Configuration

The extension reads the project `.env` and supports these optional overrides:

- `PI_DICTATE_INPUT_DEVICE` (default `PowerConf`)
- `PI_DICTATE_FFMPEG` (default `/opt/homebrew/bin/ffmpeg`)
- `PI_DICTATE_OMLX_BASE_URL` (otherwise `OMLX_BASE_URL`)
- `PI_DICTATE_OMLX_API_KEY` (otherwise `OMLX_API_KEY`)
- `PI_DICTATE_OMLX_MODEL` (default `whisper-large-v3-turbo-asr-4bit`)
- `PI_DICTATE_LANGUAGE` (default `en`)
- `PI_DICTATE_PREVIEW_INTERVAL_MS` (default `1200`)

## Permissions

VS Code must be enabled under **System Settings → Privacy & Security → Microphone**. The standard macOS Dictation F1 hotkey remains disabled so F1 reaches VS Code and Pi.
