package local.jarvis.monitor;

import java.io.ByteArrayOutputStream;
import java.net.DatagramPacket;
import java.net.InetAddress;
import java.net.MulticastSocket;
import java.net.NetworkInterface;
import java.net.InetSocketAddress;
import java.net.SocketTimeoutException;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;

/** Bounded, exact-service IPv4 mDNS lookup. Results are UNTRUSTED routing hints.
 * Legacy-unicast queries use an ephemeral port, so no multicast receive lock,
 * native Android NSD channel, broad service scan or new permission is needed.
 * Client independently enforces the original identity and certificate pin.
 */
public final class MdnsDiscovery {
    private static final int LIMIT = 4096;
    public static final class Endpoint {
        public final String address;
        public final int port;
        Endpoint(String address, int port) { this.address = address; this.port = port; }
    }
    public static final class Answer {
        public final String owner, target, address;
        public final int port;
        Answer(String owner, String target, String address, int port) {
            this.owner = owner; this.target = target; this.address = address; this.port = port;
        }
    }
    public static boolean privateV4(byte[] ip) {
        if (ip == null || ip.length != 4) return false;
        int a = ip[0] & 255, b = ip[1] & 255;
        return a == 10 || (a == 172 && b >= 16 && b <= 31) || (a == 192 && b == 168);
    }
    private static int u16(byte[] b, int p) throws Exception {
        if (p < 0 || p + 2 > b.length) throw new Exception("Truncated DNS");
        return ((b[p] & 255) << 8) | (b[p + 1] & 255);
    }
    private static String name(byte[] b, int[] cursor) throws Exception {
        int p = cursor[0], end = -1, jumps = 0, size = 0;
        StringBuilder text = new StringBuilder();
        while (true) {
            if (p >= b.length || ++jumps > 128) throw new Exception("Invalid DNS name");
            int n = b[p++] & 255;
            if (n == 0) break;
            if ((n & 192) == 192) {
                if (p >= b.length) throw new Exception("Truncated DNS pointer");
                if (end < 0) end = p + 1;
                p = ((n & 63) << 8) | (b[p] & 255);
                continue;
            }
            if (n > 63 || p + n > b.length || (size += n + 1) > 254)
                throw new Exception("Invalid DNS label");
            if (text.length() > 0) text.append('.');
            for (int i = 0; i < n; i++) {
                int ch = b[p++] & 255;
                if (ch <= 32 || ch >= 127 || ch == '.') throw new Exception("Invalid DNS label");
                text.append((char)ch);
            }
        }
        cursor[0] = end < 0 ? p : end;
        return text.toString().toLowerCase(Locale.US);
    }
    private static void encodedName(ByteArrayOutputStream out, String value) throws Exception {
        for (String label : value.split("\\.")) {
            byte[] raw = label.getBytes("US-ASCII");
            if (raw.length == 0 || raw.length > 63) throw new Exception("Invalid query");
            out.write(raw.length); out.write(raw);
        }
        out.write(0);
    }
    public static byte[] query(String owner, int type) throws Exception {
        if (owner.length() > 253 || (type != 1 && type != 33)) throw new Exception("Invalid query");
        ByteArrayOutputStream out = new ByteArrayOutputStream();
        out.write(new byte[]{0,0,0,0,0,1,0,0,0,0,0,0});
        encodedName(out, owner);
        out.write(type >> 8); out.write(type & 255); out.write(0); out.write(1);
        return out.toByteArray();
    }
    public static List<Answer> answers(byte[] packet) throws Exception {
        List<Answer> result = new ArrayList<Answer>();
        if (packet.length < 12 || packet.length > LIMIT || u16(packet, 0) != 0 ||
                (u16(packet, 2) & 0xfa0f) != 0x8000) throw new Exception("Invalid DNS response");
        int questions = u16(packet, 4), count = u16(packet, 6) + u16(packet, 8) + u16(packet, 10);
        if (questions > 8 || count > 64) throw new Exception("Oversized DNS response");
        int[] p = {12};
        for (int i = 0; i < questions; i++) { name(packet, p); u16(packet, p[0] + 2); p[0] += 4; }
        for (int i = 0; i < count; i++) {
            String owner = name(packet, p);
            int at = p[0], type = u16(packet, at), cls = u16(packet, at + 2) & 0x7fff;
            int length = u16(packet, at + 8), data = at + 10, end = data + length;
            if (end > packet.length) throw new Exception("Truncated DNS data");
            boolean alive = false;
            for (int k = at + 4; k < at + 8; k++) alive |= packet[k] != 0;
            if (cls == 1 && alive && type == 33) {
                if (length < 7) throw new Exception("Truncated SRV");
                int port = u16(packet, data + 4); int[] targetAt = {data + 6};
                String target = name(packet, targetAt);
                if (targetAt[0] != end || !target.endsWith(".local") || port < 1)
                    throw new Exception("Invalid SRV");
                result.add(new Answer(owner, target, null, port));
            } else if (cls == 1 && alive && type == 1 && length == 4) {
                byte[] ip = java.util.Arrays.copyOfRange(packet, data, end);
                if (privateV4(ip)) result.add(new Answer(owner, null,
                    InetAddress.getByAddress(ip).getHostAddress(), 0));
            }
            p[0] = end;
        }
        return result;
    }
    public static Endpoint match(String service, List<Answer> records) {
        for (Answer srv : records) {
            if (!service.equalsIgnoreCase(srv.owner) || srv.target == null) continue;
            for (Answer a : records)
                if (a.address != null && srv.target.equals(a.owner)) return new Endpoint(a.address, srv.port);
        }
        return null;
    }
    public static Endpoint resolve(String service, InetAddress local) throws Exception {
        if (!privateV4(local.getAddress())) return null;
        long deadline = System.nanoTime() + 1800000000L;
        List<Answer> records = new ArrayList<Answer>();
        try (MulticastSocket socket = new MulticastSocket(new InetSocketAddress(local, 0))) {
            socket.setNetworkInterface(NetworkInterface.getByInetAddress(local));
            socket.setTimeToLive(255);
            InetAddress group = InetAddress.getByName("224.0.0.251");
            byte[] request = query(service, 33);
            socket.send(new DatagramPacket(request, request.length, group, 5353));
            String queriedTarget = null;
            for (int i = 0; i < 16; i++) {
                long remaining = deadline - System.nanoTime();
                if (remaining <= 0) break;
                socket.setSoTimeout((int)Math.max(1, remaining / 1000000));
                byte[] buffer = new byte[LIMIT + 1];
                DatagramPacket response = new DatagramPacket(buffer, buffer.length);
                try { socket.receive(response); } catch (SocketTimeoutException e) { break; }
                if (response.getPort() != 5353 || !privateV4(response.getAddress().getAddress()) ||
                        response.getLength() > LIMIT) continue;
                try { records.addAll(answers(java.util.Arrays.copyOf(buffer, response.getLength()))); }
                catch (Exception invalid) { continue; }
                Endpoint found = match(service, records);
                if (found != null) return found;
                for (Answer a : records) if (service.equalsIgnoreCase(a.owner) && a.target != null &&
                        !a.target.equals(queriedTarget)) {
                    queriedTarget = a.target; byte[] q = query(a.target, 1);
                    socket.send(new DatagramPacket(q, q.length, group, 5353));
                    break;
                }
            }
        }
        return null;
    }
    private MdnsDiscovery() {}
}
