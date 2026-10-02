# Resolve automation research — September 9, 2026

## Conclusion
Resolve is a credible fit for agent-assisted rough editing followed by human finishing in the same editable project. The previous failed external connection and UI import attempt do not establish a lack of editing capability. No researched third-party installer or script was executed.

## Official installed API evidence
Read `/Applications/DaVinci Resolve.app/Contents/Resources/Developer/Scripting/README.txt`:
- `CreateEmptyTimeline`, `AppendToTimeline` with source ranges, media type, track index and record frame.
- `ImportTimelineFromFile` supports OTIO, DRT, XML/FCPXML and others.
- Timeline markers, clip properties, title insertion, project save/export.
These permit editable timeline construction, not merely flattened movie rendering. They do not imply every UI editing operation is exposed.

## Relevant public implementations
1. https://github.com/web594/resolve-multicam-workflow
   Explicit goal: automate multicamera preparation/rough cutting so a human finishes in Resolve Studio. Includes audio correlation, cut plans, titles, grading and verification. Inspected actual `vorlagen/apply_cut.py`: uses Resolve API to build source-range video edits and audio segments, then saves the project. Their native multicam approach builds/patches DRT structures; this is more fragile than an official native multicam API. Templates include project-specific Windows paths and timeline deletion; do not run unchanged. Speech-oriented cut planning is not automatically suitable for music.
2. https://github.com/samuelgursky/davinci-resolve-mcp
   AI-to-Resolve API tooling. Its README reports a free-edition in-app authenticated loopback bridge tested on macOS Resolve 21.0.3.7. This is author-reported, not tested on this installation. It warns of version-dependent scripting restrictions (including newer free releases). External scripting is the Studio path; inspect installed edition/version before choosing a connection method. An MCP server is optional—we could build a smaller guarded bridge for Pi.
3. https://github.com/samuelgursky/davinci-resolve-mcp/blob/main/docs/guides/multicam-setup-guide.md
   Clearly distinguishes per-camera stacked editable timeline preparation from native multicam creation, angle switching and flattening, which it says are not exposed by the public API. Supports explicit record-frame offsets, compatible with our existing cue-free audio alignment.
4. https://github.com/allwavemedia/resolve-ai-toolkit
   Another Studio-focused agent/MCP integration. Documentary evidence of an existing ecosystem, not an assurance its full feature set is reliable here.

## Connection and scope caveats
- External `scriptapp('Resolve')` has failed locally; installed product edition has not been conclusively identified. Bundle display name alone is not proof of Free versus Studio.
- Third-party reports of successful bridges are not local validation. Review authentication, loopback binding, command scope, teardown and version compatibility before installing.
- Official forum search results corroborate Studio's external-scripting requirement, but selected forum pages could not be fetched (403/blocked host); do not present those as fully inspected pages.
- A native multicam clip is different from a normal editable timeline that cuts between synchronized camera sources. The latter is adequate for an initial automated rough cut and is a safer first target.
- Our existing OTIO already describes editable clips; Python/FFmpeg can be analysis helpers while Resolve remains the user-facing editor.

## Recommended proof of concept
1. Identify exact installed edition/version and establish a read-only API connection. Prefer Studio Local scripting if already available; otherwise investigate the version-appropriate in-app route. No purchase recommendation before this check.
2. Import only the existing verified take into a dedicated project, with no GUI click automation for clip edits.
3. Preserve `Synced Sources`; create a separate `Rough Cut v001` with source-linked camera cuts, continuous master audio and review markers.
4. Validate track placement, VFR interpretation and source paths; save the project.
5. User changes a cut and title directly in Resolve. Demonstrate the handoff before expanding automation. Future agent revisions go into a new timeline rather than overwriting human work.

Native multicam conversion and advanced grading/effects can remain human steps initially. REAPER/live music sessions remain untouched.
