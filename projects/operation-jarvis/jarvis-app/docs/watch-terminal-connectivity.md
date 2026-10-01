# Watch terminal connectivity validation

## Recovery changes

- Frame GETs use a separate pinned URLSession: 7-second request timeout and
  9-second resource timeout. Input/history and speech sessions keep their prior
  timeout settings. Input POSTs are never automatically replayed.
- Wake recovery waits `candidate route count * 9 + 2` seconds without a successful
  poll before rebuilding. This permits a full sequential fallback cycle instead
  of cancelling it after seven seconds. A successful poll cancels recovery;
  normal failures remain the retry loop's responsibility.
- Transport-level URL cancellation is retried/falls back unless the owning Task
  is actually cancelled. Previously it could terminate the poll loop while the
  controller still retained the completed task.
- Failed frame routes are deprioritized for 15 seconds, not excluded. Successful
  routes remain preferred. No authentication or certificate checks are relaxed.
- Last-frame retention and input confirmation gates are unchanged.

## Diagnostics

Use macOS Console with the attached Watch selected. Filter for categories
`terminal` and `terminal-network`.

- `terminal_start`: installed app version/build.
- Lifecycle and `route_restart` events: background/visibility resets.
- `frame_transport_failure`: numeric route index, URLError code, elapsed seconds.
- `frame_http_failure`: numeric HTTP status, without response body.
- `frame_certificate_rejected`, `frame_invalid_response`: validation failures.
- `route_selected`, `route_confirmed`: successful recovery.
- `wake_recovery_stalled`: bounded wake watchdog fired.

Route indices refer to the configured candidate order. Logs do not include
endpoint addresses, credentials, request bodies, or terminal content.

## Physical-device acceptance (not replaced by simulator builds)

Compare old/new builds on the same Watch and network:

1. Record version/build and five minutes of foreground terminal use.
2. Repeat ten wrist-down/wrist-up cycles, then ten leave/return cycles.
3. Test supported network transitions with/without the paired phone nearby.
4. With explicit operator permission, test endpoint unavailability and recovery.
5. Send individual keys and text before/after recovery; confirm no duplicate
   input, and that disconnected controls remain disabled.

Record poll failures per minute, seconds with controls disabled, wake-to-ready
latency, and recovery route for each case. Check that healthy wrist raises do
not generate route restarts. A true background suspension is expected to close
networking and require fresh confirmation on return. Do not claim reduced
physical-device dropout rates until these measurements have been taken.
