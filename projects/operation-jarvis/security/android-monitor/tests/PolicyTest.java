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
        eq("wake", p.consider("nearby", 2, 5000, true)); p.applied("nearby");
        eq("none", p.consider("nearby", 2, 10000, true));
        eq("none", p.consider("away", 2, 15000, true));
        eq("sleep", p.consider("away", 2, 20000, true)); p.applied("away");
        eq("none", p.consider("away", 2, 25000, true));
        eq("none", p.consider("nearby", 16, 30000, true));
        eq("none", p.consider("nearby", -1, 35000, true));
        eq("none", p.consider("nearby", Double.POSITIVE_INFINITY, 40000, true));
        eq("none", p.consider("nearby", 2, 45000, false));
        eq("wake", p.consider("nearby", 2, 50000, true)); p.applied("nearby");
        eq("none", p.consider("away", 2, 55000, true));
        eq("none", p.consider("unknown", Double.NaN, 60000, true));
        eq("none", p.consider("away", 2, 65000, true));
        eq("none", p.consider("away", 2, 90000, true)); // gap resets
        eq("none", p.consider("away", 2, 89000, true)); // clock reversal resets
        eq("sleep", p.consider("away", 2, 94000, true));
        Policy restored = new Policy("away");
        eq("none", restored.consider("away", 1, 0, true));
        eq("none", restored.consider("away", 1, 5000, true));
        eq("wake", restored.consider("nearby", 1, 10000, true));
        System.out.println(checks + " policy assertions passed.");
    }
}
