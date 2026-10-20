package local.jarvis.monitor;

/** Readback only: never invent presence, unlock, enable, or issue a screen action. */
public final class DisplayRecovery {
    public static boolean admitted(String state, double age, boolean powered) {
        return powered && !Double.isNaN(age) && !Double.isInfinite(age) && age >= 0 && age <= 15 &&
            ("nearby".equals(state) || "away".equals(state));
    }
    public static boolean observed(String state, boolean interactive, boolean keyguardLocked) {
        return "nearby".equals(state) ? interactive :
            "away".equals(state) && !interactive && keyguardLocked;
    }
    public static long delay(int failures) {
        return Math.min(60000L, 5000L << Math.min(4, Math.max(0, failures)));
    }
}
