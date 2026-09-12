# Simulator showcase

[Project overview](../../README.md)

These screenshots and the video were captured from the JARVIS apps in Apple simulators, using read-only sample data. The owner reviewed and approved the exports. Each includes a sample-data label, even when viewed outside this page.

## Assets

- [iPhone and Watch overview](jarvis-simulator-overview.png)
- [Eight-second interface-motion showcase](jarvis-simulator-showcase.mp4)
- [iPhone Home](iphone-home.png)
- [iPhone Jobs](iphone-jobs.png)
- [Watch System](watch-system.png)
- [Watch Jobs](watch-jobs.png)

The eight-second video puts the two simulator recordings side by side to show the UI animations. It does not run a task, call a model, or control a device. It has no audio.

## Capture provenance

- Base source: [`1888cdd`](https://github.com/DylPickle13/JARVIS/commit/1888cdd), including the application code already present at `a810484`.
- Targets: iPhone 11 simulator and Apple Watch Series 11 (46 mm) simulator, iOS/watchOS 26.5.
- Both Debug simulator builds succeeded. The full regression suite was not run, and no signed device release was made.
- The capture builds used an isolated checkout, separate bundle/Keychain namespaces and URL scheme, loopback-only default API endpoints, and a disabled paired-device bridge. None of these capture-only changes went into the production app.
- A local fixture server returned generated state, quota, model-status, schedule, and result examples. It had no upstream connections and rejected all writes. The capture request log contained only GET requests.
- No live credentials, conversations, scheduled jobs, provider requests, or device controls were used. Quota, air-quality, and activity values are examples.
- Screenshot processing adds external captions and scales the overview layout. It does not redraw application controls. The video is trimmed, scaled, composited, and encoded as silent H.264 with no copied source metadata.

## Publication scope

Only the six approved media files are published, not raw logs, desktop screenshots, build products, simulator containers, or the private capture workspace. Review privacy and obtain owner approval again before adding or replacing captures.
