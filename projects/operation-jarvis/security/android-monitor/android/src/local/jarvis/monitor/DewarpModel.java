package local.jarvis.monitor;

/** Approximate centred equidistant lens, not a manufacturer calibration.
 * Output-to-input mapping: atan(r*k)/(r*k). Radius is in half-image-width units.
 * Centre scale is unchanged; stronger correction crops more of the periphery.
 */
public final class DewarpModel {
    public static final int DEFAULT_MODE = 3; // Owner-selected Strong; saved manual choices take precedence.
    private static final float[] STRENGTH = {0f, 0.8f, 1.2f, 1.55f};
    private static final String[] LABEL = {"original", "mild", "medium", "strong"};
    public static int valid(int mode) { return mode >= 0 && mode < STRENGTH.length ? mode : 0; }
    public static int next(int mode) { return (valid(mode) + 1) % STRENGTH.length; }
    public static float strength(int mode) { return STRENGTH[valid(mode)]; }
    public static String label(int mode) { return LABEL[valid(mode)]; }
    public static double scale(double radius, int mode) {
        double t = radius * strength(mode);
        return t < 0.00001 ? 1.0 : Math.atan(t) / t;
    }
    private DewarpModel() {}
}
