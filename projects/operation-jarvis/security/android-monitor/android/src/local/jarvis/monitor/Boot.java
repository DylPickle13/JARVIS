package local.jarvis.monitor;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
public final class Boot extends BroadcastReceiver {
    @Override public void onReceive(Context c, Intent i) {
        String action = i.getAction();
        boolean boot = Intent.ACTION_BOOT_COMPLETED.equals(action);
        boolean power = Intent.ACTION_POWER_CONNECTED.equals(action);
        boolean updated = Intent.ACTION_MY_PACKAGE_REPLACED.equals(action);
        // Resume only an already-enabled, non-pending helper after an in-place update.
        // Keep the last applied presence state; no forced wake or acknowledged errors.
        if (!boot && !power && !updated) return;
        SharedPreferences p = c.getSharedPreferences("monitor", 0);
        if (p.getBoolean("enabled", false) && !p.getBoolean("pending", false)) {
            if (boot) p.edit().remove("applied").commit();
            c.startService(new Intent(c, MonitorService.class));
        }
    }
}
