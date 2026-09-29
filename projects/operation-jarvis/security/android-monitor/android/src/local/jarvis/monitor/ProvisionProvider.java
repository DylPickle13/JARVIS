package local.jarvis.monitor;
import android.content.*;
import android.database.Cursor;
import android.net.Uri;
import android.os.Binder;
import android.os.Bundle;
import android.util.Base64;
import java.io.File;
import java.io.FileOutputStream;
import java.net.URL;
import org.json.JSONObject;

/** One-time USB-shell provisioning into internal storage, never APK assets.
 * Both signature-level DUMP permission and exact shell UID are required.
 * No readback API; later replacement requires clearing app data deliberately.
 */
public final class ProvisionProvider extends ContentProvider {
    @Override public boolean onCreate() { return true; }
    @Override public synchronized Bundle call(String method, String arg, Bundle extras) {
        if (Binder.getCallingUid() != 2000) throw new SecurityException("USB shell only");
        Bundle result = new Bundle();
        if (!"provision".equals(method)) { result.putString("status", "unsupported"); return result; }
        File file = new File(getContext().getFilesDir(), "client.json");
        if (file.exists()) { result.putString("status", "already-provisioned"); return result; }
        try {
            String encoded = extras == null ? null : extras.getString("config");
            if (encoded == null || encoded.length() > 8192) throw new Exception();
            byte[] raw = Base64.decode(encoded, Base64.NO_WRAP);
            JSONObject config = new JSONObject(new String(raw, "UTF-8"));
            URL url = new URL(config.getString("url"));
            if (!"https".equals(url.getProtocol()) || !"/v1/presence".equals(url.getPath()) ||
                    url.getUserInfo() != null || url.getQuery() != null || url.getRef() != null ||
                    config.getString("token").length() < 32 ||
                    !config.getString("certificateSha256").matches("[0-9a-f]{64}")) throw new Exception();
            File temp = new File(getContext().getFilesDir(), "client.tmp");
            FileOutputStream out = getContext().openFileOutput("client.tmp", Context.MODE_PRIVATE);
            try { out.write(raw); out.getFD().sync(); } finally { out.close(); }
            if (!temp.renameTo(file)) throw new Exception();
            result.putString("status", "provisioned");
        } catch (Exception e) { result.putString("status", "failed"); }
        return result;
    }
    @Override public Cursor query(Uri u, String[] p, String s, String[] a, String o) { throw new UnsupportedOperationException(); }
    @Override public String getType(Uri u) { return null; }
    @Override public Uri insert(Uri u, ContentValues v) { throw new UnsupportedOperationException(); }
    @Override public int delete(Uri u, String s, String[] a) { throw new UnsupportedOperationException(); }
    @Override public int update(Uri u, ContentValues v, String s, String[] a) { throw new UnsupportedOperationException(); }
}
