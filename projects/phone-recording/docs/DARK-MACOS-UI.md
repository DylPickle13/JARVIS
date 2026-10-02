# Dark macOS-inspired interface

Visual-only refresh of `dashboard/index.html`, `style.css`, and `app.js`.

- Dark-only system typography, compact toolbar, neutral camera tiles and blue primary action. No simulated traffic-light window controls or native-Apple-material claim.
- Restrained translucent panels with fine borders and shadows; opaque fallback where backdrop filters or reduced transparency require it. Reduced-motion preference disables transitions.
- Compact battery/storage/temperature summaries; full cached camera details retain configured format, transport, power, observation time, blockers and warnings. Unknown values display dashes, not healthy defaults. Last-observation/staleness remains visible.
- Less routine text. Recording/uncertain states, connection-loss warnings, recovery, typed scope-specific deletion confirmation and both review pauses remain unchanged.
- Pipeline details are collapsed by default; live processing status remains visible in the session heading. Library, Activity and camera details remain accessible.
- No camera/controller, transfer, deletion, sync, Resolve, authentication or REAPER changes. No new recordings, phone commands or preview captures were made for this refresh.

Validation: 186 automated tests pass, plus JavaScript syntax checking. Isolated Chrome exercises 36 UI assertions at each of 1440×900, 1280×720, 1024×650 and 900×600, including four-camera snapshots, deletion at both review pauses, active-operation guards, dark-only styling, compact metrics, and no scrolling with the pipeline expanded. Live Chrome inspected at 1920×873. No server restart is necessary for static assets; reload the dashboard to get the current interface.
