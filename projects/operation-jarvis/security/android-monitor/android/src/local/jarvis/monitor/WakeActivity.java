package local.jarvis.monitor;
import android.app.Activity;
import android.app.KeyguardManager;
import android.content.Intent;
import android.os.Bundle;
import android.os.Handler;
import android.view.WindowManager;

/** Only dismisses an insecure swipe keyguard. Never attempts secure unlock. */
public final class WakeActivity extends Activity {
    private final Handler handler = new Handler();
    private int attempts;
    @Override public void onCreate(Bundle b) {
        super.onCreate(b);
        KeyguardManager k = (KeyguardManager)getSystemService(KEYGUARD_SERVICE);
        if (k.isKeyguardSecure()) { finish(); return; }
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_TURN_SCREEN_ON |
            WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON |
            WindowManager.LayoutParams.FLAG_DISMISS_KEYGUARD);
        handler.postDelayed(new Runnable() {
            @Override public void run() {
                KeyguardManager kg = (KeyguardManager)getSystemService(KEYGUARD_SERVICE);
                if (kg.isKeyguardSecure()) { finish(); return; }
                if (kg.isKeyguardLocked() && ++attempts < 10) {
                    handler.postDelayed(this, 300); return;
                }
                if (!kg.isKeyguardLocked()) {
                    Intent viewer = PlayerLauncher.intent(WakeActivity.this);
                    if (viewer != null) startActivity(viewer);
                }
                finish();
            }
        }, 300);
    }
    @Override public void onDestroy() { handler.removeCallbacksAndMessages(null); super.onDestroy(); }
}
