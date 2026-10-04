import local.jarvis.monitor.MdnsDiscovery;
import java.io.ByteArrayOutputStream;
import java.util.Arrays;

public class MdnsDiscoveryTest {
    static int checks;
    static final String SERVICE = "JARVIS-0123456789abcdef0123456789abcdef._jarvis-monitor._tcp.local";
    static void check(boolean ok) { checks++; if (!ok) throw new AssertionError("check " + checks); }
    static void u16(ByteArrayOutputStream b, int n) { b.write(n >> 8); b.write(n & 255); }
    static byte[] dnsName(String name) throws Exception {
        byte[] q = MdnsDiscovery.query(name, 1);
        return Arrays.copyOfRange(q, 12, q.length - 4);
    }
    static byte[] packet(String service, String target, byte[] ip, int ttl) throws Exception {
        ByteArrayOutputStream b = new ByteArrayOutputStream();
        b.write(new byte[]{0,0,(byte)0x84,0,0,1,0,1,0,0,0,1});
        byte[] q = MdnsDiscovery.query(service, 33); b.write(q, 12, q.length - 12);
        u16(b, 0xc00c); u16(b, 33); u16(b, 0x8001); b.write(new byte[]{0,0,0,(byte)ttl});
        byte[] host = dnsName(target); u16(b, 6 + host.length);
        u16(b, 0); u16(b, 0); u16(b, 8794); int targetAt = b.size(); b.write(host);
        u16(b, 0xc000 | targetAt); u16(b, 1); u16(b, 1); b.write(new byte[]{0,0,0,(byte)ttl});
        u16(b, ip.length); b.write(ip); return b.toByteArray();
    }
    static void bad(byte[] p) {
        boolean rejected = false;
        try { MdnsDiscovery.answers(p); } catch (Exception e) { rejected = true; }
        check(rejected);
    }
    public static void main(String[] args) throws Exception {
        byte[] privateIp = {(byte)192,(byte)168,21,100};
        byte[] good = packet(SERVICE, "mac-mini.local", privateIp, 120);
        MdnsDiscovery.Endpoint e = MdnsDiscovery.match(SERVICE, MdnsDiscovery.answers(good));
        check(e != null && e.port == 8794 && e.address.equals("192.168.21.100"));
        check(MdnsDiscovery.match(SERVICE.toLowerCase(), MdnsDiscovery.answers(good)) != null);
        check(MdnsDiscovery.match("different._jarvis-monitor._tcp.local", MdnsDiscovery.answers(good)) == null);
        check(MdnsDiscovery.match(SERVICE, MdnsDiscovery.answers(packet(SERVICE,"mac.local",privateIp,0))) == null);
        check(MdnsDiscovery.match(SERVICE, MdnsDiscovery.answers(packet(SERVICE,"mac.local",new byte[]{8,8,8,8},120))) == null);
        check(MdnsDiscovery.match(SERVICE, MdnsDiscovery.answers(packet(SERVICE,"mac.local",new byte[16],120))) == null);
        check(MdnsDiscovery.privateV4(new byte[]{10,1,2,3}));
        check(MdnsDiscovery.privateV4(new byte[]{(byte)172,16,2,3}));
        check(!MdnsDiscovery.privateV4(new byte[]{(byte)172,32,2,3}));
        check(!MdnsDiscovery.privateV4(new byte[]{127,0,0,1}));
        check(!MdnsDiscovery.privateV4(new byte[]{(byte)169,(byte)254,0,1}));
        check(!MdnsDiscovery.privateV4(new byte[]{100,64,0,1}));
        bad(new byte[5]); bad(new byte[4097]); bad(MdnsDiscovery.query(SERVICE,33));
        bad(Arrays.copyOf(good, good.length - 1));
        byte[] loop = good.clone(); loop[12] = (byte)0xc0; loop[13] = 12; bad(loop);
        byte[] outside = good.clone(); outside[12] = (byte)0xff; outside[13] = (byte)0xff; bad(outside);
        byte[] opcode = good.clone(); opcode[2] = (byte)0x8c; bad(opcode);
        byte[] truncatedFlag = good.clone(); truncatedFlag[2] |= 2; bad(truncatedFlag);
        byte[] id = good.clone(); id[1] = 1; bad(id);
        byte[] hugeCount = good.clone(); hugeCount[7] = 65; bad(hugeCount);
        bad(packet(SERVICE,"untrusted.example",privateIp,120));
        byte[] invalidLabel = good.clone(); invalidLabel[12] = 64; bad(invalidLabel);
        System.out.println(checks + " scoped mDNS assertions passed.");
    }
}
