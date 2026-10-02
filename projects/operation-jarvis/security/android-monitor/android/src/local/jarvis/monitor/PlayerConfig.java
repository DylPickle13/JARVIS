package local.jarvis.monitor;

/** Pure input validation; no secret is ever included in an exception message. */
public final class PlayerConfig {
    public static boolean valid(String host, int port, String path, String user, String password) {
        if (host == null || path == null || user == null || password == null || port != 554 ||
                !(path.equals("/stream1") || path.equals("/stream2")) ||
                user.length() < 1 || user.length() > 256 || password.length() < 1 || password.length() > 256 ||
                user.indexOf(':') >= 0 || hasControl(user) || hasControl(password)) return false;
        String[] parts = host.split("\\.", -1);
        if (parts.length != 4) return false;
        int[] ip = new int[4];
        try {
            for (int i = 0; i < 4; i++) {
                if (!parts[i].matches("0|[1-9][0-9]{0,2}")) return false;
                ip[i] = Integer.parseInt(parts[i]);
                if (ip[i] > 255) return false;
            }
        } catch (Exception e) { return false; }
        return ip[0] == 10 || (ip[0] == 172 && ip[1] >= 16 && ip[1] <= 31) ||
            (ip[0] == 192 && ip[1] == 168);
    }
    private static boolean hasControl(String value) {
        for (int i = 0; i < value.length(); i++) if (value.charAt(i) < 32 || value.charAt(i) == 127) return true;
        return false;
    }
}
