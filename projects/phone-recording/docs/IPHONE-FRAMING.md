# iPhone framing investigation — September 9, 2026

## Dashboard integration

**Check framing now includes LG, Samsung and iPhone.** All enabled cameras must be idle, with no pending take; capture holds the shared controller lock. iPhone uses a bounded (45-second) one-shot Network-only DVT connection and closes every resource before returning. PNG input and resized JPEG output are validated; remote temporary files are removed. A failed iPhone capture rejects the whole framing result rather than showing a misleading partial set.

Local previews expire after 60 seconds, clear before Start, clear on a failed preview job and on dashboard-server restart. Server-side cache housekeeping runs even with the browser closed; if the server itself is stopped, cleanup occurs when restarted. No images are stored in durable job results. No photo is saved on a phone.

Code: `iphone_preview.py`, `framing_preview.py`, `camera-config.json`, dashboard job/server/UI modules. Overhead remains disabled. 129 automated tests pass, including Network/identity guards, capture failure/timeout teardown, three-camera routing, partial-result cleanup and browser-independent expiry. The live dashboard button successfully displayed all three views in Chrome; no recording was started.

## Follow-up: Network screenshot succeeded

With user authorization, the newer developer path successfully returned a **4,838,867-byte screenshot** from this iPhone. Visually verified the Blackmagic Camera screen and live desk/monitor framing. Every enabled camera was idle before and after. No photo was saved on the phone; temporary PNG/JPEG previews on both Macs were removed after inspection.

- Developer Mode **and a personalized developer image were already enabled/mounted**. Nothing was downloaded or mounted by this investigation; do not unmount the pre-existing image as cleanup.
- Native remote discovery returned no devices; both legacy Screenshotr and direct-lockdown DVT returned InvalidService. An initial screenshot attempt was correctly deferred for an LG unknown observation; an observation-only recheck passed.
- Successful route: identity-checked, `autopair=False`, explicit **Network** lockdown → `CoreDeviceTunnelProxy` → in-process userspace TCP tunnel → identity-checked RemoteServiceDiscovery → DVT Screenshot. No root, new trust, OS daemon, USB fallback, media session or camera-settings change.
- All acquired screenshot, RSD, tunnel and lockdown resources closed before returning. No continuous preview remains. REAPER untouched.
- Reusable diagnostic: `diagnostics/iphone_framing_probe.py`, remote `.iphone-venv` only. Default captures once and discards bytes after reporting size. Run as a dedicated process; the SDK userspace transport selector is process-global. The equivalent inline probe was hardware-tested; the extracted diagnostic was syntax-checked, not separately re-run.
- **Now integrated into dashboard Check framing**, with the guards and tests above. A successful one-shot does not prove reboot or long-session reliability.

The initial investigation below is retained as history; its legacy-service failure is not a statement that iPhone remote framing is impossible.

No recording, photo creation/deletion, app switching or camera-settings changes were performed. REAPER untouched.

## Verified on the configured iPhone

- Pinned Wi-Fi GET `/control/documentation.html` supplied the installed app's API specifications.
- Reviewed camera, monitoring, video, live-stream, clips and transport specifications. No still-photo capture or single preview-image endpoint found in these specifications. Monitoring endpoints configure overlays/output; clips describes existing clips, not a current live image. Saved relevant additional YAML under `docs/wifi-api-docs/`.
- Existing-pairing **Network-only** lockdown metadata reported `DeveloperModeStatus: true`. This investigation did not enable Developer Mode.
- Under the shared camera lock, with no pending take and all three cameras confirmed idle, attempted the existing `com.apple.mobile.screenshotr` developer service once. It returned `InvalidServiceError: InvalidService`; no image was obtained or saved.
- All three cameras remained idle afterward. No image mount, tunnel installation, new pairing or transport fallback was attempted.

## Options and limits

1. **Developer screenshot route:** worth investigating further. pymobiledevice3 documents developer-image prerequisites and DVT screenshot support; modern iOS can require the remote developer/tunnel path. Developer Mode alone did not make the legacy screenshot service available. Would need a separately approved setup/validation step. A successful streamed screenshot need not create a Photos-library item.
2. **Blackmagic remote monitoring:** officially supported between compatible controller devices, including Macs. Potentially open only for framing then disconnect before Start; not yet integrated or tested. The public specifications inspected do not expose a one-shot image URL. A preview session is not a phone-local photo.
3. **Separate photo workflow:** a camera app/Shortcut could potentially capture an approximate framing image, but remote triggering, return to Blackmagic, lens/crop differences, settings preservation and exact temporary-image cleanup are unimplemented/unverified. Switching apps can interrupt the active camera session. Do not promise an unattended photo-and-delete operation or invoke broad Photos deletion.
4. **Short throwaway video:** not used; this is still a recording and requires explicit authorization plus managed inventory/verified collection/cleanup, not an undocumented framing side effect.

Recommended next investigation: supported developer screenshot path, avoiding a camera-app switch and permanent phone image creation. Currently the iPhone screen remains the proven framing method.

References:
- https://www.blackmagicdesign.com/products/blackmagiccamera
- https://doronz88.github.io/pymobiledevice3/cli/developer/
