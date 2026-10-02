package local.jarvis.monitor;

/** Owner-selected audio-on default. Mute/focus loss survives reconnect, not a new foreground session. */
public final class ListenAudioPolicy {
    private boolean available, listening;
    private boolean requested = true, pending = true;
    public void reset() { requested = true; closed(); }
    public void closed() { available = false; listening = false; pending = requested; }
    public void tracks(boolean playable) {
        available = playable;
        if (!available) listening = false;
    }
    public boolean autoRequested() { return available && requested && pending; }
    public boolean unmute(boolean foregroundUnlocked, boolean focusGranted) {
        pending = false;
        listening = available && foregroundUnlocked && focusGranted;
        requested = listening; // Denial fails closed; track callbacks cannot retry focus.
        return listening;
    }
    public void mute() { listening = requested = pending = false; }
    public boolean available() { return available; }
    public boolean listening() { return listening; }
}
