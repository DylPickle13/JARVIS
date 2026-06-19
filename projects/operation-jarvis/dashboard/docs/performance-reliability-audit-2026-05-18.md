# Dashboard performance + reliability audit — 2026-05-18

Scope: Operation JARVIS dashboard room display, browser camera client, Node dashboard server, and docs.

## Changes made

- Removed always-running visual effects from the room display path:
  - no starfield canvas or startup code,
  - no decorative HUD pulse/rotation/scan overlay,
  - no touch ripple / button scale / arc-reactor touch pulse,
  - final CSS motion guard keeps the alarm display static.
- Removed hidden/no-op decorative DOM nodes (`noise`, `aurora`) from `public/index.html`.
- Changed the browser camera preview to stay off by default for lower power use.
  - Tap the preview to start it manually.
  - Use `?camera=1` or `?cam=1` when auto-start is intentionally wanted.
- Reduced repeated browser layout/DOM work:
  - the clock only writes DOM text when displayed values actually change,
  - camera panel repositioning is no longer queued every second by the clock tick.
- Reduced static GPU-heavy styling on the hologram background by disabling the alarm-display SVG filter/drop-shadow blend.
- Cleaned dead code:
  - removed unused `escapeHtml()` from `public/display.js`,
  - removed unused `activeDiscordSessionHasProcess()` from `src/server.mjs`.
- Hardened server behavior:
  - static file serving now uses `path.relative()` containment checks instead of prefix-only matching,
  - debug endpoints accept both documented `JARVIS_ENABLE_DASHBOARD_DEBUG_ENDPOINTS` and legacy `JARVIS_DASHBOARD_DEBUG_ENDPOINTS`.
- Updated dashboard and Operation JARVIS docs to match the new low-power camera/default-animation behavior.

## Validation run

```bash
cd /path/to/JARVIS/projects/operation-jarvis/dashboard
npm run check
npm run url
```

```bash
cd /path/to/JARVIS/projects/operation-jarvis
python3 -m compileall -q -x '(^|/)(\.venv|__pycache__|media|data)(/|$)' .
```

Live server smoke check while the dashboard service was already running:

```bash
curl http://127.0.0.1:8787/api/status
curl http://127.0.0.1:8787/api/jarvis/display | python3 -m json.tool
curl http://127.0.0.1:8787/manifest.webmanifest
```

Observed `/api/jarvis/display`: `ok=true`, state `idle`, weather `ok=true`, oMLX `ok=true`.

## Backlog / follow-ups

- Consider splitting the legacy cockpit CSS from the active alarm-clock CSS. `public/styles.css` is still large because it contains old dashboard skin rules that the current root display does not use.
- Consider extending `npm run check` with a tiny no-dependency smoke test for `/api/status`, `/api/jarvis/display`, and static asset serving.
- Consider a production cache policy that keeps `index.html` no-store but allows content-hashed static assets to cache. Current no-store is convenient for rapid local iteration.
