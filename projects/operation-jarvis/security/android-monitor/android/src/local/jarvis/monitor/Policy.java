package local.jarvis.monitor;

/** Pure transition policy; unknown/power loss/gaps break consecutive-away checks. */
public final class Policy {
    private String applied;
    private int awayCount = 0;
    private long last = -1;
    public Policy(String applied) { this.applied = applied; }
    public String consider(String state, double age, long now, boolean powered) {
        if (last < 0 || now < last || now - last > 15000) awayCount = 0;
        last = now;
        if (!powered || Double.isNaN(age) || Double.isInfinite(age) || age < 0 || age > 15 ||
                !(state.equals("nearby") || state.equals("away"))) {
            awayCount = 0;
            return "none";
        }
        if (state.equals("nearby")) {
            awayCount = 0;
            return applied.equals("nearby") ? "none" : "wake";
        }
        awayCount = Math.min(2, awayCount + 1);
        return awayCount >= 2 && !applied.equals("away") ? "sleep" : "none";
    }
    public void applied(String state) { applied = state; }
}
