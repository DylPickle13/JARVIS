import local.jarvis.monitor.DisplayRecovery;
public final class DisplayRecoveryTest {
    static void check(boolean value) { if (!value) throw new AssertionError(); }
    public static void main(String[] args) {
        check(DisplayRecovery.admitted("nearby",0,true));
        check(DisplayRecovery.admitted("away",15,true));
        for(double age:new double[]{-1,16,Double.NaN,Double.POSITIVE_INFINITY})
            check(!DisplayRecovery.admitted("nearby",age,true));
        check(!DisplayRecovery.admitted("unknown",0,true));
        check(!DisplayRecovery.admitted("nearby",0,false));
        check(DisplayRecovery.observed("nearby",true,true)); // Wake never promises unlock.
        check(!DisplayRecovery.observed("nearby",false,false));
        check(DisplayRecovery.observed("away",false,true));
        check(!DisplayRecovery.observed("away",true,true));
        check(!DisplayRecovery.observed("away",false,false));
        check(!DisplayRecovery.observed("unknown",false,true));
        check(DisplayRecovery.delay(0)==5000);
        check(DisplayRecovery.delay(1)==10000);
        check(DisplayRecovery.delay(Integer.MAX_VALUE)==60000);
        System.out.println("Display recovery admission/readback checks passed; no Android actions.");
    }
}
