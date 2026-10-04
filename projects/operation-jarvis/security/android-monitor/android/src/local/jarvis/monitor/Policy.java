package local.jarvis.monitor;

/** Follow completed computer-display actions; no independent away debounce.
 * The authenticated v2 relay gates startup, freshness, faults and transitions.
 * Unknown/power loss leaves the phone unchanged; successful modes are not replayed.
 */
public final class Policy {
    private String applied;
    public Policy(String applied) { this.applied = applied; }
    public String consider(String state, double age, long now, boolean powered) {
        if (!powered || Double.isNaN(age) || Double.isInfinite(age) || age < 0 || age > 15 ||
                !(state.equals("nearby") || state.equals("away"))) return "none";
        if (applied.equals(state)) return "none";
        return state.equals("nearby") ? "wake" : "sleep";
    }
    public void applied(String state) { applied = state; }
}
