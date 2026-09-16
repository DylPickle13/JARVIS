# Watch purifier rows

Build179: Watch-only deployment; iPhone178 and backend176 stay unchanged.
The former68pt purifier panel is now two30pt rows plus4pt top/bottom padding.
Each row shows its name, status/mode and PM2.5. Both devices remain visible;
there is no picker. Shared neutral Watch surface, purple icons, no extra card tint.
Tapping opens a scrolling sheet with the full device name, readings, filter,
standard-size power/mode/fan buttons and explicit refresh/recovery actions.
The sheet captures its immutable target ID. Missing selected devices never fall
back to the default; command confirmation and busy identity use that target.
Pending verification disables writes. No cloud reads on row taps or sheet lifecycle;
the existing explicit System-page refresh remains. No physical purifier writes in testing.
Sheet/dialog coverage suspends dashboard paging, crown/oMLX interactions as before.

Validation: shared row model tests,100iOS tests including24Watch-size renders
(162/184/208, normal/accessibility, normal/stale/pending/off/highPM/offline),
68pt assertions; Watch target compilation and actual watchOS26.5 simulator System
capture. These are not watchOS27 runtime/endurance or physical tap-target acceptance.
Fixed compact text preserves the height; VoiceOver exposes full names/readings,
while the detail sheet uses Dynamic Type.30pt row targets require owner acceptance.
An initial narrow render truncated Dylan's; status/PM columns were narrowed before release.
Existing terminal, toolbar, clipboard, Neural Core/artwork/40frames, Siri, widgets,
Jobs, phone UI, backend/cloud scheduling and shared Watch wire types are unchanged.
