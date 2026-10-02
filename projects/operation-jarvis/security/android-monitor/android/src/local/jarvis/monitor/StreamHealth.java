package local.jarvis.monitor;

/** Constant-space stream watchdog. No frame storage or unbounded retry queue. */
public final class StreamHealth {
    private long began, lastFrame, steadySince;
    private int lastDecoded = -1, failures;
    public void opened(long now) { began = now; lastFrame = now; steadySince = 0; lastDecoded = -1; }
    public boolean stalled(int decoded, long now) {
        if (decoded > 0 && decoded != lastDecoded) {
            lastFrame = now;
            if (steadySince == 0) steadySince = now;
            if (now - steadySince >= 60000) failures = 0;
        }
        lastDecoded = decoded;
        return now >= began && now - lastFrame >= 30000;
    }
    public long retryDelay() {
        long[] delays = {5000, 10000, 20000, 30000, 60000};
        steadySince = 0;
        return failures < delays.length ? delays[failures++] : -1;
    }
    public void reset() { failures = 0; }
}
