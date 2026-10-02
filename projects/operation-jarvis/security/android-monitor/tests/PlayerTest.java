import local.jarvis.monitor.PlayerConfig;
import local.jarvis.monitor.StreamHealth;
public class PlayerTest {
    static int checks;
    static void check(boolean value) { checks++; if (!value) throw new AssertionError("check " + checks); }
    static boolean valid(String host, int port, String path, String user, String pass) {
        return PlayerConfig.valid(host, port, path, user, pass);
    }
    public static void main(String[] args) {
        for (String host : new String[]{"192.168.1.2","10.1.2.3","172.16.1.2","172.31.255.254"})
            check(valid(host,554,"/stream2","test","dummy"));
        for (String host : new String[]{"127.0.0.1","8.8.8.8","172.32.0.1","172.15.0.1","169.254.1.1",
                "::1","camera.local","192.168.001.2","192.168.1.999","192.168.1","192.168.1.1/evil","",null})
            check(!valid(host,554,"/stream2","test","dummy"));
        check(!valid("10.1.2.3",80,"/stream2","test","dummy"));
        check(!valid("10.1.2.3",554,"/other","test","dummy"));
        check(!valid("10.1.2.3",554,"/stream2","a:b","dummy"));
        check(!valid("10.1.2.3",554,"/stream2","test","\nsecret"));
        check(!valid("10.1.2.3",554,"/stream2","","dummy"));
        check(valid("10.1.2.3",554,"/stream1","test","colon: percent% at@"));
        StreamHealth h = new StreamHealth(); h.opened(1000);
        check(!h.stalled(0,30999)); check(h.stalled(0,31000));
        check(h.retryDelay()==5000); h.opened(40000);
        check(!h.stalled(1,41000)); check(!h.stalled(2,42000));
        check(!h.stalled(2,71999)); check(h.stalled(2,72000));
        check(h.retryDelay()==10000); check(h.retryDelay()==20000);
        check(h.retryDelay()==30000); check(h.retryDelay()==60000);
        check(h.retryDelay()==-1); check(h.retryDelay()==-1);
        h.opened(100000);
        for (int i=1;i<=32;i++) check(!h.stalled(i,100000+i*2000));
        check(h.retryDelay()==5000); // healthy stream renews bounded budget
        h.reset(); check(h.retryDelay()==5000); // explicit owner/session reset
        System.out.println(checks + " player assertions passed.");
    }
}
