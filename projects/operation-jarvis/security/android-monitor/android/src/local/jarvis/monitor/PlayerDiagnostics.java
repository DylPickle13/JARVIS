package local.jarvis.monitor;

/** Drops all library logging; retains only whitelisted protocol tokens, never headers/URIs. */
final class PlayerDiagnostics implements com.google.android.exoplayer2.util.Log.Logger {
    static volatile String protocol = "";
    static volatile int sdpVideoTracks;
    static void reset() { protocol = ""; sdpVideoTracks = 0; }
    @Override public void d(String tag, String message) {
        if (!"RtspClient".equals(tag)) return;
        String token = null;
        if (message.startsWith("RTSP/1.0 ") && message.length() >= 12 && message.substring(9,12).matches("[0-9]{3}"))
            token = message.substring(9,12);
        for (String method : new String[]{"OPTIONS","DESCRIBE","SETUP","PLAY","PAUSE","TEARDOWN","GET_PARAMETER"})
            if (message.startsWith(method + " ")) token = method;
        if (token != null) {
            String next = protocol + " " + token;
            protocol = next.length() > 180 ? next.substring(next.length()-180) : next;
        }
        if (message.contains("\nm=video ")) sdpVideoTracks++;
    }
    @Override public void i(String tag, String message) {}
    @Override public void w(String tag, String message) {}
    @Override public void e(String tag, String message) {}
}
