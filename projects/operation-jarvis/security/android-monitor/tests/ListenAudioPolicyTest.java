import local.jarvis.monitor.ListenAudioPolicy;
public class ListenAudioPolicyTest {
    static int checks;
    static void check(boolean value) { checks++; if (!value) throw new AssertionError("check " + checks); }
    public static void main(String[] args) {
        ListenAudioPolicy p = new ListenAudioPolicy();
        check(!p.available()); check(!p.listening()); check(!p.autoRequested());
        p.tracks(false); check(!p.autoRequested()); // Empty discovery must not cancel default.
        p.tracks(true); check(p.autoRequested());
        check(p.unmute(true,true)); check(p.listening()); check(!p.autoRequested());
        p.tracks(true); check(!p.autoRequested()); // No repeated focus requests.
        p.closed(); check(!p.listening()); check(!p.available());
        p.tracks(true); check(p.autoRequested()); // Reconnect restores an on choice.
        check(p.unmute(true,true));
        p.mute(); check(!p.listening()); check(!p.autoRequested());
        p.tracks(true); check(!p.autoRequested());
        p.closed(); p.tracks(true); check(!p.autoRequested()); // Mute survives reconnect.
        p.reset(); p.tracks(true); check(p.autoRequested()); // New foreground defaults on.
        for (boolean available : new boolean[]{false, true}) {
            for (boolean eligible : new boolean[]{false, true}) {
                for (boolean focus : new boolean[]{false, true}) {
                    p.reset(); p.tracks(available);
                    check(!p.listening());
                    check(p.autoRequested() == available);
                    check(p.unmute(eligible, focus) == (available && eligible && focus));
                    check(p.listening() == (available && eligible && focus));
                    check(!p.autoRequested());
                    p.mute(); check(!p.listening()); check(p.available() == available);
                }
            }
        }
        p.reset(); p.tracks(true); check(!p.unmute(true,false));
        p.tracks(true); check(!p.autoRequested()); // Focus denied: no callback retry.
        p.closed(); p.tracks(true); check(!p.autoRequested()); // Nor reconnect retry.
        check(p.unmute(true,true)); // Explicit user tap may try again.
        p.mute(); p.closed(); p.tracks(true); check(!p.autoRequested()); // Loss/noisy stays muted.
        p.reset(); check(!p.listening()); p.tracks(true); check(p.autoRequested());
        check(p.unmute(true,true)); p.tracks(false);
        check(!p.listening()); check(!p.autoRequested()); // Missing audio never plays.
        System.out.println(checks + " listen-audio assertions passed.");
    }
}
