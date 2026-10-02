package com.google.android.exoplayer2.source.rtsp;
import android.net.Uri;

/** Run with app_process against the installed APK; synthetic credentials only. */
public final class PlayerUriTest {
    static int checks;
    static void eq(Object expected, Object actual) {
        checks++;
        if (!expected.equals(actual)) throw new AssertionError("URI regression check " + checks);
    }
    public static void main(String[] args) {
        String target = "rtsp://192.168.40.12:554/stream2";
        String[][] values = {{"camera", "secret"}, {"camera@example.invalid", "p@ssword"},
            {"a@@b", "colon:percent%slash/at@"}, {"space user", "pass with spaces"}};
        for (String[] pair : values) {
            Uri uri = Uri.parse("rtsp://" + Uri.encode(pair[0]) + ":" + Uri.encode(pair[1]) + "@192.168.40.12:554/stream2");
            eq(target, RtspMessageUtil.removeUserInfo(uri).toString());
            eq("192.168.40.12", RtspMessageUtil.removeUserInfo(uri).getHost());
            eq(pair[0], RtspMessageUtil.parseUserInfo(uri).username);
            eq(pair[1], RtspMessageUtil.parseUserInfo(uri).password);
        }
        eq(target, RtspMessageUtil.removeUserInfo(Uri.parse(target)).toString());
        System.out.println(checks + " on-device RTSP URI assertions passed.");
    }
}
