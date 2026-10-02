package local.jarvis.monitor;
import android.app.*;
import android.app.admin.DevicePolicyManager;
import android.content.*;
import android.os.*;
import android.view.View;
import android.widget.*;

public final class MainActivity extends Activity {
    private final Handler handler = new Handler();
    private TextView status;
    private SharedPreferences prefs;
    private final Runnable refresh = new Runnable() { @Override public void run() {
        String enabled = prefs.getBoolean("enabled", false) ? "Enabled" : "Disabled";
        String contact = MonitorService.lastContact == 0 ? "No successful connection yet" :
            "Last authenticated response: " + ((SystemClock.elapsedRealtime() - MonitorService.lastContact) / 1000) + " seconds ago";
        status.setText(enabled + "\n" + MonitorService.status + "\n" + contact +
            (prefs.getBoolean("pending", false) ? "\nAn interrupted action needs your review." : ""));
        handler.postDelayed(this, 1000);
    }};
    @Override public void onCreate(Bundle b) {
        super.onCreate(b);
        prefs = getSharedPreferences("monitor", 0);
        ScrollView scroll = new ScrollView(this);
        LinearLayout body = new LinearLayout(this); body.setOrientation(LinearLayout.VERTICAL); body.setPadding(36, 18, 36, 18);
        scroll.addView(body); setContentView(scroll);
        TextView title = new TextView(this); title.setText("JARVIS Monitor"); title.setTextSize(24); body.addView(title);
        TextView info = new TextView(this);
        info.setText("Uses basement presence, like Computer presence. Nearby: wake + camera viewer. Two fresh away checks: lock/sleep. Unknown: unchanged.\nKeep on a wall charger and home Wi-Fi. Device Administrator grants ONLY screen locking, not wipe or password changes. Secure locks still require your PIN.\nThe app starts after reboot if enabled. Disable here before removing Administrator permission or uninstalling.");
        info.setTextSize(16); body.addView(info);
        status = new TextView(this); status.setTextSize(17); body.addView(status);
        button(body, "1. Grant screen-lock permission", new View.OnClickListener() { public void onClick(View v) {
            Intent i = new Intent(DevicePolicyManager.ACTION_ADD_DEVICE_ADMIN);
            i.putExtra(DevicePolicyManager.EXTRA_DEVICE_ADMIN, new ComponentName(MainActivity.this, Admin.class));
            i.putExtra(DevicePolicyManager.EXTRA_ADD_EXPLANATION, "Allow JARVIS to turn off this monitor when basement presence reports away. Only force-lock is requested.");
            startActivity(i);
        }});
        button(body, "2. Enable / acknowledge reviewed error", new View.OnClickListener() { public void onClick(View v) {
            DevicePolicyManager d = (DevicePolicyManager)getSystemService(DEVICE_POLICY_SERVICE);
            if (!d.isAdminActive(new ComponentName(MainActivity.this, Admin.class))) {
                Toast.makeText(MainActivity.this, "Grant screen-lock permission first", Toast.LENGTH_LONG).show(); return;
            }
            stopService(new Intent(MainActivity.this, MonitorService.class));
            if (prefs.edit().putBoolean("enabled", true).putBoolean("pending", false).remove("applied").commit())
                startService(new Intent(MainActivity.this, MonitorService.class));
        }});
        button(body, "Disable automation", new View.OnClickListener() { public void onClick(View v) {
            prefs.edit().putBoolean("enabled", false).commit();
            stopService(new Intent(MainActivity.this, MonitorService.class));
            MonitorService.status = "Stopped by owner; screen unchanged";
        }});
        CheckBox nativePlayer = new CheckBox(this);
        nativePlayer.setText("Use private camera viewer (uncheck for tinyCam fallback)");
        nativePlayer.setEnabled(PlayerLauncher.configured(this));
        nativePlayer.setChecked(PlayerLauncher.configured(this) && prefs.getBoolean("native_player", true));
        nativePlayer.setOnCheckedChangeListener(new CompoundButton.OnCheckedChangeListener() {
            public void onCheckedChanged(CompoundButton button, boolean checked) {
                prefs.edit().putBoolean("native_player", checked).commit();
            }
        });
        body.addView(nativePlayer);
        button(body, "Test: sleep then wake in 8 seconds", new View.OnClickListener() { public void onClick(View v) {
            if (prefs.getBoolean("enabled", false)) startService(new Intent(MainActivity.this, MonitorService.class).setAction("local.jarvis.monitor.SELF_TEST"));
        }});
        button(body, "Open camera viewer", new View.OnClickListener() { public void onClick(View v) {
            Intent i = PlayerLauncher.intent(MainActivity.this);
            if (i != null) startActivity(i);
        }});
    }
    private void button(LinearLayout parent, String text, View.OnClickListener listener) {
        Button button = new Button(this); button.setText(text); button.setOnClickListener(listener); parent.addView(button);
    }
    @Override public void onResume() { super.onResume(); handler.post(refresh); }
    @Override public void onPause() { handler.removeCallbacksAndMessages(null); super.onPause(); }
}
