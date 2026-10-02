import local.jarvis.monitor.DewarpModel;

public final class DewarpModelTest {
    private static int assertions;
    private static void check(boolean value) { assertions++; if (!value) throw new AssertionError(); }
    private static void near(double a, double b) { check(Math.abs(a-b) < 0.00001); }
    public static void main(String[] args) {
        check(DewarpModel.DEFAULT_MODE == 3);
        check(DewarpModel.label(DewarpModel.DEFAULT_MODE).equals("strong"));
        check(DewarpModel.valid(-1) == 0); check(DewarpModel.valid(4) == 0);
        check(DewarpModel.valid(Integer.MAX_VALUE) == 0);
        int mode = 0;
        for (int i=0; i<4; i++) { check(mode == i); mode = DewarpModel.next(mode); }
        check(mode == 0);
        for (int m=0; m<4; m++) {
            near(DewarpModel.scale(0, m), 1);
            double previous = -1;
            for (int i=0; i<=200; i++) {
                double r = i / 100.0, s = DewarpModel.scale(r,m), mapped = r*s;
                check(Double.isFinite(s) && s > 0 && s <= 1);
                check(mapped > previous); previous = mapped; // No folds/reversed edges.
                if (m == 0) near(s, 1);
                else check(s <= DewarpModel.scale(r,m-1));
            }
            // 4:3, 16:9 and portrait: bounded coordinates, centre, radial symmetry.
            for (double aspect : new double[]{4.0/3,16.0/9,3.0/4}) {
                for (int x=-10; x<=10; x++) for (int y=-10; y<=10; y++) {
                    double px=x/10.0, py=y/(10.0*aspect);
                    double s=DewarpModel.scale(Math.hypot(px,py),m);
                    check(Math.abs(px*s) <= 1.000001 && Math.abs(py*s*aspect) <= 1.000001);
                    near(s,DewarpModel.scale(Math.hypot(-px,-py),m));
                }
            }
            if (m == 0) continue;
            // Analytic round-trip for a straight vertical line through an equidistant lens.
            double k = DewarpModel.strength(m);
            for (int i=-100; i<=100; i++) {
                double x=0.6, y=i/100.0;
                double scale=DewarpModel.scale(Math.hypot(x,y),m);
                double sx=x*scale, sy=y*scale, sr=Math.hypot(sx,sy);
                double inverse=Math.tan(sr*k)/(sr*k);
                near(sx*inverse,x); near(sy*inverse,y);
            }
        }
        System.out.println(assertions + " dewarp assertions passed.");
    }
}
