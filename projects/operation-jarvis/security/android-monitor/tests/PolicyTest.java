import local.jarvis.monitor.Policy;
public class PolicyTest {
    static int checks;
    static void eq(String expected, String actual) {
        checks++;
        if (!expected.equals(actual)) throw new AssertionError(expected + " != " + actual);
    }
    public static void main(String[] args) {
        Policy p = new Policy("");
        eq("none", p.consider("unknown", Double.NaN, 0, true));
        eq("wake", p.consider("nearby", 2, 1000, true)); p.applied("nearby");
        eq("none", p.consider("nearby", 2, 2000, true));
        eq("none", p.consider("unknown", Double.NaN, 3000, true));
        // The first completed computer sleep is enough: no second phone timer.
        eq("sleep", p.consider("away", 2, 4000, true)); p.applied("away");
        eq("none", p.consider("away", 2, 5000, true));
        eq("none", p.consider("nearby", 16, 6000, true));
        eq("none", p.consider("nearby", -1, 7000, true));
        eq("none", p.consider("nearby", Double.POSITIVE_INFINITY, 8000, true));
        eq("none", p.consider("nearby", Double.NaN, 9000, true));
        eq("none", p.consider("nearby", 2, 10000, false));
        eq("wake", p.consider("nearby", 2, 11000, true)); p.applied("nearby");
        eq("none", p.consider("bogus", 2, 12000, true));
        eq("none", p.consider("away", 20, 13000, true));
        eq("none", p.consider("away", 2, 14000, false));
        Policy restored = new Policy("away");
        eq("none", restored.consider("away", 1, 0, true));
        eq("wake", restored.consider("nearby", 1, 1000, true));
        Policy fresh = new Policy("");
        eq("none", fresh.consider("unknown", Double.NaN, 0, true));
        eq("sleep", fresh.consider("away", 0, 1000, true));
        System.out.println(checks + " synchronized policy assertions passed.");
    }
}
