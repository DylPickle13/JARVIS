# JARVIS Watch companion packaging, deployment, and recovery

**Last updated:** 2026-08-20
**Applies to:** Xcode 26, iOS 26, watchOS 26, XcodeGen 2.46, Personal Team/free provisioning
**Status:** package identity, installation, icons, and both installed flags pass; the final physical reachability/relay matrix remains open

This is the canonical operational runbook for the JARVIS iPhone/Apple Watch
companion. Read it before changing target relationships, bundle IDs, signing,
installation, or WatchConnectivity code.

Do not commit hardware identifiers, provisioning profiles, certificates,
captured logs, screenshots, exported IPAs, archives, or DerivedData. Keep device
identities in environment variables and retain the Dylan-only deployment guards.
Never unpair or erase the Watch during recovery.

## 1. Required identity and metadata

Use this exact hierarchy:

| Product | Bundle identifier |
|---|---|
| iPhone app | `com.operation-jarvis.jarvis` |
| iPhone widget | `com.operation-jarvis.jarvis.widget` |
| Watch app | `com.operation-jarvis.jarvis.watchkitapp` |
| Watch widget/complication | `com.operation-jarvis.jarvis.watchkitapp.widget` |

Xcode 26 derives an attached Watch app as:

```text
<existing iOS bundle identifier>.watchkitapp
```

Do not use the earlier `.watch` suffix. A separately installed `.watch` build
can launch and can even become reachable, but the iPhone does not recognize it
as this parent app's companion.

The Watch `Info.plist` must contain:

```xml
<key>WKApplication</key>
<true/>
<key>WKCompanionAppBundleIdentifier</key>
<string>com.operation-jarvis.jarvis</string>
<key>WKRunsIndependentlyOfCompanionApp</key>
<false/>
```

`WKWatchOnly` must be absent. Build 5 established that the dependent value
`WKRunsIndependentlyOfCompanionApp=false` is required for the current companion:
the Watch then reported `isCompanionAppInstalled=true`.

All four products derive these values from shared build settings:

```xml
<key>CFBundleShortVersionString</key>
<string>$(MARKETING_VERSION)</string>
<key>CFBundleVersion</key>
<string>$(CURRENT_PROJECT_VERSION)</string>
```

Keep the iPhone app, Watch app, and both widgets on one build number. Increment
it after any identity, metadata, target-relationship, or embedding change.

## 2. Canonical target relationship and embedding

The decisive build-6 fix was the iPhone target's explicit Watch dependency:

```yaml
- target: JARVISWatch
  platforms: [iOS]
  platformFilter: iOS
  embed: true
```

The signed archive/export pipeline then accepted this layout:

```text
JARVIS.app/
├── PlugIns/
│   └── JARVISWidget.appex
└── Watch/
    └── JARVISWatch.app
        └── PlugIns/
            └── JARVISWatchWidget.appex
```

For this Xcode 26 single-target Watch companion, the canonical embedded path is:

```text
JARVIS.app/Watch/JARVISWatch.app
```

The copy phase must have:

```text
dstPath = "$(CONTENTS_FOLDER_PATH)/Watch"
dstSubfolderSpec = 16   # Watch
```

`scripts/patch-watch-embedding.sh` enforces that destination after XcodeGen.
Keep it configured through `options.postGenCommand` and keep the generated
project reproducible. Do not hand-edit `project.pbxproj`.

Earlier `PlugIns/JARVISWatch.app` experiments built, signed, and launched, but
did not give the iPhone a registered available companion. Build success and an
installed Watch icon were therefore not proof of a valid parent relationship.

## 3. Required Watch target settings and assets

Keep these settings in `project.yml`:

```yaml
PRODUCT_BUNDLE_IDENTIFIER: com.operation-jarvis.jarvis.watchkitapp
PRODUCT_NAME: JARVISWatch
INFOPLIST_FILE: JARVISWatch/Info.plist
GENERATE_INFOPLIST_FILE: NO
ALWAYS_EMBED_SWIFT_STANDARD_LIBRARIES: YES
ASSETCATALOG_COMPILER_APPICON_NAME: WatchAppIcon
GENERATE_PKGINFO_FILE: YES
SDKROOT: watchos
SKIP_INSTALL: YES
TARGETED_DEVICE_FAMILY: "4"
WRAPPER_EXTENSION: app
WATCHOS_DEPLOYMENT_TARGET: "10.0"
```

Do **not** set `ALLOW_TARGET_PLATFORM_SPECIALIZATION=YES` on the Watch app
target. In a combined iOS-simulator build, that setting caused Xcode 26 to
compile `JARVISWatch` for physical watchOS while Swift Package dependencies
were compiled for the Watch simulator, producing:

```text
unable to resolve module dependency: 'JARVISKit'
```

Removing it restores the combined iOS/watchOS simulator build and preserves the
signed generic-device build and `Watch/` embedding.

The canonical icon source is:

```text
projects/operation-jarvis/jarvis-icon.png
```

The generated iOS 1024 px icon and every required Watch launcher,
notification, settings, quick-look, and marketing icon must be square and
opaque. `scripts/verify-jarvis-app.sh` checks all required dimensions and
rejects alpha channels. The built plists must name `AppIcon` and
`WatchAppIcon` respectively.

## 4. Signing checks for a Personal Team

Personal Team provisioning supports these development app products, but it
does not provide App Groups or shared cross-target Keychain access. Do not add
those entitlements as a packaging workaround.

Audit the archive or signed generic-device product:

```bash
APP="$ARCHIVE/Products/Applications/JARVIS.app"
WATCH="$APP/Watch/JARVISWatch.app"
WATCH_WIDGET="$WATCH/PlugIns/JARVISWatchWidget.appex"
PHONE_WIDGET="$APP/PlugIns/JARVISWidget.appex"

codesign --verify --deep --strict --verbose=4 "$APP"
codesign -d --entitlements :- "$APP" 2>/dev/null
codesign -d --entitlements :- "$WATCH" 2>/dev/null
codesign -d --entitlements :- "$WATCH_WIDGET" 2>/dev/null
codesign -d --entitlements :- "$PHONE_WIDGET" 2>/dev/null
```

Expected:

- all products use the configured Personal Team;
- each `application-identifier` matches its bundle identifier;
- nested profiles include every development device needed by the archive/export
  operation;
- profiles are unexpired;
- no App Group entitlement is present;
- `codesign --verify --deep --strict` passes.

A passing signature is necessary but does not prove parent registration,
installation ownership, installed flags, or reachability.

## 5. Installation sources are not equivalent

### CoreDevice iPhone installation

This command is appropriate for iPhone-only iteration:

```bash
xcrun devicectl device install app \
  --device "$PHONE_COREDEVICE_ID" \
  "$APP"
```

The iPhone installer records:

```text
Setting skip watch app install flag
```

That option deliberately skips companion reconciliation. Do not use this route
as proof of Watch registration.

### IPA installation through the iPhone service

A signed IPA installed through `ideviceinstaller` does not request the
CoreDevice skip-Watch option. With the corrected target relationship, this
registered JARVIS as a locally available companion and made it appear under
Apple's Watch app.

### Apple Watch app / Bridge installation

The consumer Watch app can display JARVIS under **Available Apps**, but a
Personal Team build cannot complete installation from that source. The remote
Watch installer returned:

```text
MIInstallerErrorDomain Code=111
ApplicationVerificationFailed
The bundle ... is authorized by a free provisioning profile, but apps
validated by those are not allowed to be installed from this source.
```

The generic user-facing alert is:

```text
This app could not be installed at this time.
```

Retrying **Install** cannot fix this. It is a free-profile source restriction,
not an icon, bundle-ID, signature, tunnel, or trust failure.

### Xcode/CoreDevice Watch developer installation

A direct developer install is allowed for the free profile. After the corrected
parent IPA was registered on the iPhone, installing the exact Watch product
from that same archive completed the relationship:

```bash
xcrun devicectl device install app \
  --device "$WATCH_COREDEVICE_ID" \
  "$ARCHIVE/Products/Applications/JARVIS.app/Watch/JARVISWatch.app"
```

After this combined parent-registration/developer-install path:

```text
iPhone: paired=true installed=true
Watch:  companionAppInstalled=true
```

A direct Watch install **by itself** is still not authoritative. The installed
flags passed only after the corrected parent package was already registered on
the iPhone.

## 6. Canonical build, archive, and export

Generate the project and run local verification first:

```bash
cd projects/operation-jarvis/jarvis-app
xcodegen generate
./scripts/verify-jarvis-app.sh
```

Create the signed archive with Xcode's supported pipeline:

```bash
rm -rf "$ARCHIVE" "$DERIVED_DATA"

xcodebuild \
  -project JARVIS.xcodeproj \
  -scheme JARVIS \
  -configuration Debug \
  -destination 'generic/platform=iOS' \
  -archivePath "$ARCHIVE" \
  -derivedDataPath "$DERIVED_DATA" \
  DEVELOPMENT_TEAM="$TEAM_ID" \
  CODE_SIGN_STYLE=Automatic \
  -allowProvisioningUpdates \
  archive
```

Use a local, uncommitted export-options plist:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>method</key><string>debugging</string>
  <key>destination</key><string>export</string>
  <key>signingStyle</key><string>automatic</string>
  <key>teamID</key><string>YOUR_TEAM_ID</string>
  <key>manageAppVersionAndBuildNumber</key><false/>
</dict></plist>
```

Export:

```bash
rm -rf "$EXPORT_PATH"
xcodebuild \
  -exportArchive \
  -archivePath "$ARCHIVE" \
  -exportPath "$EXPORT_PATH" \
  -exportOptionsPlist "$EXPORT_OPTIONS" \
  -allowProvisioningUpdates
```

Audit the IPA and built metadata:

```bash
IPA="$EXPORT_PATH/JARVIS.ipa"
APP="$ARCHIVE/Products/Applications/JARVIS.app"
WATCH="$APP/Watch/JARVISWatch.app"
WATCH_WIDGET="$WATCH/PlugIns/JARVISWatchWidget.appex"

unzip -l "$IPA" | grep 'Payload/JARVIS.app/Watch/JARVISWatch.app/Info.plist'
codesign --verify --deep --strict --verbose=2 "$APP"

/usr/libexec/PlistBuddy -c 'Print :CFBundleIdentifier' "$APP/Info.plist"
/usr/libexec/PlistBuddy -c 'Print :CFBundleIdentifier' "$WATCH/Info.plist"
/usr/libexec/PlistBuddy -c 'Print :WKCompanionAppBundleIdentifier' "$WATCH/Info.plist"
/usr/libexec/PlistBuddy -c 'Print :WKRunsIndependentlyOfCompanionApp' "$WATCH/Info.plist"
/usr/libexec/PlistBuddy -c 'Print :CFBundleIconName' "$WATCH/Info.plist"
/usr/libexec/PlistBuddy -c 'Print :CFBundleIdentifier' "$WATCH_WIDGET/Info.plist"
```

Required values:

```text
com.operation-jarvis.jarvis
com.operation-jarvis.jarvis.watchkitapp
com.operation-jarvis.jarvis
false
WatchAppIcon
com.operation-jarvis.jarvis.watchkitapp.widget
```

Also assert that `JARVIS.app/PlugIns/JARVISWatch.app` does not exist.

## 7. Canonical free-profile deployment sequence

Use identifiers only from private environment variables. `devicectl` uses a
CoreDevice selector; `ideviceinstaller` and `idevicesyslog` use the hardware
UDID.

1. Build, archive, export, and audit as above.
2. Install or upgrade the parent without CoreDevice's skip flag:

   ```bash
   ideviceinstaller -u "$PHONE_UDID" install "$IPA"
   ```

3. If this was a clean install, trust the development profile on the iPhone:
   **Settings → General → VPN & Device Management → Developer App → Trust**.
4. Launch the iPhone app once.
5. Do not use **My Watch → Available Apps → Install** for a free-profile build;
   it is expected to fail with error 111.
6. Install the exact embedded Watch product through the developer service:

   ```bash
   xcrun devicectl device install app \
     --device "$WATCH_COREDEVICE_ID" \
     "$WATCH"
   ```

7. Confirm inventory and both installed flags.
8. Only then proceed to state and command relay validation.

A first inventory query can be empty during registry synchronization. Wait and
retry before changing metadata or reinstalling.

## 8. Device and tunnel diagnostics

Use distinct variables:

```bash
PHONE_COREDEVICE_ID=...
WATCH_COREDEVICE_ID=...
PHONE_UDID=...
WATCH_UDID=...
```

Never write real values into scripts or documentation.

Check the Watch tunnel non-destructively:

```bash
xcrun devicectl list devices --timeout 30
xcrun devicectl device info details \
  --device "$WATCH_COREDEVICE_ID" \
  --timeout 30
```

Required:

- paired and booted;
- Developer Mode enabled;
- `ddiServicesAvailable: true`;
- `tunnelState: connected`.

A transient `RemotePairingError 1001` can clear on retry. Do not unpair or erase
the Watch.

Check inventory:

```bash
xcrun devicectl device info apps \
  --device "$PHONE_COREDEVICE_ID" --timeout 45 \
  | grep -E 'com\.operation-jarvis\.jarvis|JARVIS'

xcrun devicectl device info apps \
  --device "$WATCH_COREDEVICE_ID" --timeout 45 \
  | grep -E 'com\.operation-jarvis\.jarvis|JARVIS'
```

The Watch row must use `.watchkitapp` and the expected build number.

## 9. Capturing installation failures

Start iPhone syslog capture before the operation:

```bash
idevicesyslog -u "$PHONE_UDID" > /tmp/jarvis-companion-install.log 2>&1
```

Filter afterward:

```bash
grep -Ei \
  'skip watch|operation-jarvis|watchkitapp|ACX|ApplicationVerificationFailed|MIInstallerErrorDomain|failed|error' \
  /tmp/jarvis-companion-install.log
```

Interpretation:

- `Setting skip watch app install flag`: CoreDevice iPhone-only route;
- `enumerateLocallyAvailableApplications ... .watchkitapp`: parent registration
  found the embedded companion;
- placeholder transfer followed by `MIInstallerErrorDomain Code=111`: free
  profile rejected from Bridge source;
- `ProfileValidated=true`: package profile validation passed, but a clean iPhone
  install can still need explicit user trust.

Never commit logs.

## 10. WatchConnectivity validation

Launch both apps with attached consoles:

```bash
xcrun devicectl device process launch \
  --device "$PHONE_COREDEVICE_ID" \
  --terminate-existing --console --timeout 60 \
  com.operation-jarvis.jarvis

xcrun devicectl device process launch \
  --device "$WATCH_COREDEVICE_ID" \
  --terminate-existing --console --timeout 60 \
  com.operation-jarvis.jarvis.watchkitapp
```

Relevant DEBUG traces begin with:

```text
[JARVIS WatchBridge iPhone]
[JARVIS WatchBridge Watch]
[JARVIS Watch smoke]
```

The complete physical registration/relay gate requires:

- iPhone: `paired=true installed=true`;
- Watch: `companionAppInstalled=true`;
- bidirectional `reachable=true` while both apps are active;
- a Watch state request receives a state response;
- a plug command receives exactly one correlated `commandResult` or
  `commandError`;
- duplicate request IDs execute once.

Inventory, installed flags, and reachability are separate assertions.

A paired simulator smoke using a temporary local mock passed without hardware
writes: both simulator installed flags became true, both sides became reachable,
the iPhone received an acknowledgement for `type=state`, and the Watch received
`type=state`. This proves the local transport path but does not replace the
physical matrix.

## 11. Safe DEBUG relay smoke

Force direct Watch networking to fail so the command must use the iPhone:

```bash
xcrun devicectl device process launch \
  --device "$WATCH_COREDEVICE_ID" \
  --terminate-existing --console --timeout 100 \
  com.operation-jarvis.jarvis.watchkitapp -- \
  -jarvisSeedEndpoint http://127.0.0.1:9 \
  -jarvisForceEndpoint \
  -jarvisRelaySmokePlug lamp \
  -jarvisRelaySmokeState off
```

Before any physical write:

1. warn the user;
2. confirm the representative plug's canonical state;
3. first send the same desired state (`lamp off` while already off);
4. prove exactly one command/event pair;
5. then perform one reversible state change;
6. restore the original state.

Never use `plug-toggle`. Do not test purifier writes during Watch recovery; that
physical gate is intentionally suspended.

## 12. Failed assumptions to avoid

- **“The iPhone build succeeded, so the companion is valid.”** False. Build,
  archive, signing, parent registration, installation, installed flags, and
  reachability are separate gates.
- **“A Watch icon proves companion registration.”** False.
- **“The modern single-target Watch app must be in `PlugIns/`.”** False for this
  corrected Xcode 26 parent relationship. The accepted archive uses `Watch/`.
- **“Installing from Available Apps is the authoritative free-team route.”**
  False. Bridge is prohibited from installing free-profile apps.
- **“A direct Watch install can always establish the relationship.”** False. It
  completed installed flags only after the corrected parent IPA was registered.
- **“CoreDevice iPhone installation tests companion transfer.”** False. It sets
  the skip-Watch flag.
- **“`isReachable` proves installation.”** False.
- **“`ALLOW_TARGET_PLATFORM_SPECIALIZATION` belongs on the Watch app.”** False;
  it breaks the combined simulator/package build and is unnecessary here.
- **“A tunnel failure requires unpairing or erasing.”** False.
- **“The Watch suffix can be `.watch`.”** False; use `.watchkitapp`.

## 13. Non-destructive recovery order

Stop as soon as a gate passes:

1. Confirm the exact bundle-ID hierarchy.
2. Confirm `WKApplication`, companion ID, dependent-run value, and absence of
   `WKWatchOnly` in the **built** Watch plist.
3. Confirm matching build numbers and complete opaque icon catalogs.
4. Confirm the parent target dependency and `Watch/` embedding.
5. Verify all nested signatures and development-device coverage.
6. Run the local verifier and a signed generic-device build.
7. Check pairing, unlock state, Developer Mode, DDI, and tunnel.
8. Reject CoreDevice's skip-Watch iPhone route when parent registration is the
   goal.
9. Install the exported IPA through `ideviceinstaller`.
10. Trust and launch the iPhone app if required.
11. Install the exact embedded Watch product through the developer service.
12. Re-check inventory and both installed flags.
13. Launch both counterparts and capture reachability/state messaging.
14. Run the idempotent relay smoke, then one reversible physical write.

Never modify another person's phone or pairing record. Remove only JARVIS if a
clean reinstall is required.

## 14. Current checkpoint

As of the latest pass:

- JARVIS `0.2.0 (7)` is installed on the iPhone and Watch with the requested
  iOS/watchOS icon;
- the next local candidate is `0.2.0 (8)` after removing the erroneous platform
  specialization setting;
- the iPhone parent contains the Watch app under `JARVIS.app/Watch/`;
- the `.watchkitapp` and nested widget identities are correct;
- the Personal Team archive/export and deep signatures pass;
- Apple Watch app/Bridge failure was conclusively identified as free-profile
  source rejection, not a malformed bundle;
- installing the exact archive Watch product through the developer service
  succeeded;
- iPhone reports `paired=true installed=true`;
- Watch reports `companionAppInstalled=true`;
- JARVIS appears and launches on the Watch;
- the paired simulator reached both directions and delivered state using a
  write-blocking local mock;
- automated duplicate-request coverage proves one execution;
- the last attached physical consoles did not sustain `reachable=true`, so the
  physical state-request and command-result relay gates remain open;
- the lamp and purifier remain off; no hardware command was issued during the
  packaging, icon, or local-only verification work.

The next physical pass begins with both apps foregrounded, a state-only relay
round trip, and then the guarded idempotent lamp smoke. Do not repeat bundle-ID,
icon, embedding, Available Apps, or profile-source experiments.
