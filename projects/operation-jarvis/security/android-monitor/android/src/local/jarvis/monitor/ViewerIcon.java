package local.jarvis.monitor;

import android.graphics.Canvas;
import android.graphics.ColorFilter;
import android.graphics.Paint;
import android.graphics.Path;
import android.graphics.PixelFormat;
import android.graphics.Rect;
import android.graphics.drawable.Drawable;

/** Small vector UI glyphs; never handles camera frames. Lens dots show strength. */
public final class ViewerIcon extends Drawable {
    private final int kind;
    private final Paint paint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Path path = new Path();
    private int state, alpha = 255;
    public ViewerIcon(boolean lens) { this(lens ? 0 : 1); }
    public ViewerIcon(int kind) { this.kind = kind; }
    public void state(int value) { if (state != value) { state = value; invalidateSelf(); } }
    @Override public void draw(Canvas canvas) {
        Rect b = getBounds(); int save = canvas.save();
        canvas.translate(b.left, b.top); canvas.scale(b.width()/24f, b.height()/24f);
        paint.setColor(0xffffffff); paint.setAlpha(alpha);
        paint.setStrokeWidth(1.7f); paint.setStrokeCap(Paint.Cap.ROUND); paint.setStrokeJoin(Paint.Join.ROUND);
        paint.setStyle(Paint.Style.STROKE);
        if (kind == 2) { // Equalizer sliders; lit dot indicates Voice focus.
            for (int i=0; i<3; i++) {
                float x=6+i*6, y=i==1 ? 7 : 13;
                canvas.drawLine(x, 3, x, y-2, paint); canvas.drawLine(x, y+2, x, 17, paint);
                canvas.drawCircle(x, y, 2, paint);
            }
            paint.setStyle(Paint.Style.FILL); paint.setAlpha(state == 1 ? alpha : alpha/4);
            canvas.drawCircle(12, 21, 1.5f, paint);
        } else if (kind == 0) {
            canvas.drawRoundRect(3, 2, 21, 17, 3, 3, paint);
            path.reset();
            if (state == 0) { // Curved grid for original; straight grid when corrected.
                path.moveTo(9, 3); path.quadTo(6, 9.5f, 9, 16);
                path.moveTo(15, 3); path.quadTo(18, 9.5f, 15, 16);
            } else {
                path.moveTo(9, 3); path.lineTo(9, 16);
                path.moveTo(15, 3); path.lineTo(15, 16);
            }
            path.moveTo(4, 9.5f); path.lineTo(20, 9.5f); canvas.drawPath(path, paint);
            paint.setStyle(Paint.Style.FILL);
            for (int i=0; i<3; i++) {
                paint.setAlpha(i < state ? alpha : alpha/4);
                canvas.drawCircle(8+i*4, 21, 1.2f, paint);
            }
        } else {
            path.reset(); path.moveTo(3, 9); path.lineTo(7, 9); path.lineTo(12, 5);
            path.lineTo(12, 19); path.lineTo(7, 15); path.lineTo(3, 15); path.close();
            canvas.drawPath(path, paint);
            if (state == 1) {
                canvas.drawArc(9, 7, 19, 17, -55, 110, false, paint);
                canvas.drawArc(6, 3, 24, 21, -55, 110, false, paint);
            } else {
                canvas.drawLine(16, 9, 22, 15, paint); canvas.drawLine(16, 15, 22, 9, paint);
            }
        }
        canvas.restoreToCount(save);
    }
    @Override public void setAlpha(int value) { alpha = value; invalidateSelf(); }
    @Override public void setColorFilter(ColorFilter filter) { paint.setColorFilter(filter); invalidateSelf(); }
    @Override public int getOpacity() { return PixelFormat.TRANSLUCENT; }
}
