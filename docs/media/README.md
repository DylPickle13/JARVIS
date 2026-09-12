# Simulator showcase

[Project overview](../../README.md)

**Owner-approved simulator captures with sample data.** All images and video show actual JARVIS app rendering in Apple simulators using synthetic, read-only data. The sample labels are part of the exported media so the distinction remains visible outside this README.

## Assets

- [iPhone and Watch overview](jarvis-simulator-overview.png)
- [Eight-second interface-motion showcase](jarvis-simulator-showcase.mp4)
- [iPhone Home](iphone-home.png)
- [iPhone Jobs](iphone-jobs.png)
- [Watch System](watch-system.png)
- [Watch Jobs](watch-jobs.png)

The video combines two simulator recordings side by side. It shows native activity indicators with sample telemetry, not an end-to-end task execution, real inference, device-command delivery, a performance benchmark, or physical-device acceptance. No music or microphone audio is included.

## Capture provenance

- Base source: [`1888cdd`](https://github.com/DylPickle13/JARVIS/commit/1888cdd), including the application code already present at `a810484`.
- Targets: iPhone 11 simulator and Apple Watch Series 11 (46 mm) simulator, iOS/watchOS 26.5.
- Both Debug simulator builds succeeded. This capture run did not execute the full application regression suite or create a signed physical-device release.
- Builds used an isolated checkout, separate capture-only bundle/Keychain namespaces, a capture-only URL scheme, loopback-only default API endpoints, and a disabled paired-device bridge. These isolation changes are not production app changes.
- A local fixture server returned generated state, quota, model-status, schedule, and result examples. It had no upstream connections and rejected all writes. The capture request log contained only GET requests.
- No live credentials, conversations, scheduled jobs, provider requests, or physical-device controls were used. Visible quota, air-quality, and activity values are examples, not measurements from the live system.
- Screenshot processing adds external captions and scales the overview layout. It does not redraw application controls. The video is trimmed, scaled, composited, and encoded as silent H.264 with no copied source metadata.

## Publication scope

The owner approved the exact six assets listed above for publication. Raw simulator logs, desktop screenshots, build products, simulator containers, and private capture-workspace files are excluded. Future or replacement captures require a separate privacy review and owner approval.
