# Private camera viewer dependencies

The viewer uses **ExoPlayer 2.19.1** (Google/Android Open Source Project,
Apache-2.0) with its Java RTSP/TCP module and Android MediaCodec hardware decoding.
There are no downloaded native decoders, ads, WebViews, analytics or recording.

- ExoPlayer source and license: https://github.com/google/ExoPlayer/tree/r2.19.1
- AndroidX source/licenses: https://android.googlesource.com/platform/frameworks/support/
- Guava 31.1-android and failureaccess (Apache-2.0): https://github.com/google/guava
- jsr305 (BSD): https://github.com/findbugsproject/findbugs
- Checker Framework annotations (MIT): https://github.com/typetools/checker-framework
- Error Prone annotations (Apache-2.0): https://github.com/google/error-prone
- J2ObjC annotations (Apache-2.0): https://github.com/google/j2objc
- Android SDK license: https://developer.android.com/studio/terms

`player-dependencies.json` records all selected dependencies, authoritative Google
Maven/Maven Central URLs and SHA-256 hashes. The API-33 compile-platform archive was
also verified against the SHA-1 in Google's SDK repository metadata. The manifest
runtime minimum and target remain API 23; Android 6 does not need an OS upgrade.
Only player/core/RTSP components are used, not ExoPlayer's optional UI, ads, cast or
network-service integrations. Resources and transitive Java dependencies are built
from the locked artifacts; libraries, provisioned APKs and credentials are never
committed. Do not replace a checksum without reviewing the corresponding upgrade.

One source patch is applied to the locked RTSP source archive before dexing:
`RtspMessageUtil.removeUserInfo` now uses encoded authority and the final `@`,
rather than decoded authority and the first `@`. This fixes email-style usernames
and passwords containing `@`; the upstream source/license header is retained.
The original utility classes are removed from the dependency JAR to avoid duplicate
classes. On-device regression tests exercise the installed patched implementation.

ExoPlayer 2.x is a legacy, Android-6-compatible dependency; this is a dedicated
private-LAN appliance, not a general untrusted-media player. Migration to supported
Android hardware and current Media3 remains preferable for long-term maintenance.

Rejected prototype: LibVLC 3.6.5/3.5.1/3.3.14 reported failures during
LIVE555 local-source-address/session setup on this handset. No LibVLC binaries,
multicast permission, library-specific workaround or tinyCam auto-relaunch loop
is included in the final viewer.
