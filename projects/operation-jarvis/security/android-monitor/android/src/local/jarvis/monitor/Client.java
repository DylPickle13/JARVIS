package local.jarvis.monitor;
import android.content.Context;
import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.net.URL;
import java.security.MessageDigest;
import java.security.cert.X509Certificate;
import javax.net.ssl.HttpsURLConnection;
import javax.net.ssl.SSLContext;
import javax.net.ssl.TrustManager;
import javax.net.ssl.X509TrustManager;
import org.json.JSONObject;

public final class Client {
    private final JSONObject config;
    private final SSLContext tls;
    public Client(Context context) throws Exception {
        InputStream in = context.openFileInput("client.json");
        try { config = new JSONObject(read(in, 4096)); } finally { in.close(); }
        final String pin = config.getString("certificateSha256");
        tls = SSLContext.getInstance("TLSv1.2");
        tls.init(null, new TrustManager[]{new X509TrustManager() {
            public X509Certificate[] getAcceptedIssuers() { return new X509Certificate[0]; }
            public void checkClientTrusted(X509Certificate[] c, String a) throws java.security.cert.CertificateException {
                throw new java.security.cert.CertificateException("Client certificates unsupported");
            }
            public void checkServerTrusted(X509Certificate[] chain, String auth) throws java.security.cert.CertificateException {
                try {
                    if (chain.length == 0) throw new Exception();
                    chain[0].checkValidity();
                    byte[] digest = MessageDigest.getInstance("SHA-256").digest(chain[0].getEncoded());
                    StringBuilder hex = new StringBuilder();
                    for (byte b : digest) hex.append(String.format(java.util.Locale.US, "%02x", b & 255));
                    if (!MessageDigest.isEqual(hex.toString().getBytes("UTF-8"), pin.getBytes("UTF-8"))) throw new Exception();
                } catch (Exception e) { throw new java.security.cert.CertificateException("Certificate pin mismatch or expired certificate"); }
            }
        }}, null);
    }
    private static String read(InputStream in, int limit) throws Exception {
        ByteArrayOutputStream out = new ByteArrayOutputStream();
        byte[] buf = new byte[512];
        int n;
        while ((n = in.read(buf)) != -1) {
            if (out.size() + n > limit) throw new Exception("Response too large");
            out.write(buf, 0, n);
        }
        return out.toString("UTF-8");
    }
    public JSONObject poll() throws Exception {
        URL url = new URL(config.getString("url"));
        if (!url.getProtocol().equals("https")) throw new Exception("TLS required");
        HttpsURLConnection c = (HttpsURLConnection)url.openConnection();
        c.setSSLSocketFactory(tls.getSocketFactory());
        // Keep Android's normal hostname verification in addition to the certificate pin.
        c.setConnectTimeout(3000); c.setReadTimeout(3000);
        c.setInstanceFollowRedirects(false); c.setUseCaches(false);
        c.setRequestProperty("Authorization", "Bearer " + config.getString("token"));
        try {
            if (c.getResponseCode() != 200) throw new Exception("Request rejected");
            InputStream in = c.getInputStream();
            try { return new JSONObject(read(in, 1024)); } finally { in.close(); }
        } finally { c.disconnect(); }
    }
}
