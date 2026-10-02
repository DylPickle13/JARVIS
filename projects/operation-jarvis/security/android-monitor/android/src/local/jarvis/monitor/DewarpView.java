package local.jarvis.monitor;

import android.content.Context;
import android.graphics.SurfaceTexture;
import android.opengl.GLES11Ext;
import android.opengl.GLES20;
import android.opengl.GLSurfaceView;
import android.os.Handler;
import android.os.Looper;
import android.view.Surface;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.nio.FloatBuffer;
import java.util.concurrent.atomic.AtomicBoolean;
import javax.microedition.khronos.egl.EGLConfig;
import javax.microedition.khronos.opengles.GL10;

/** One hardware-decoder OES texture, one full-screen draw per available frame.
 * No CPU frame copies, bitmap queues, readbacks, recorder, or network access.
 * Owned by one foreground session; release player BEFORE shutdown().
 */
public final class DewarpView extends GLSurfaceView implements GLSurfaceView.Renderer {
    public interface Listener { void ready(Surface output); void failed(); }
    private final Listener listener;
    private final Handler main = new Handler(Looper.getMainLooper());
    private final AtomicBoolean framePending = new AtomicBoolean();
    private final FloatBuffer vertices = ByteBuffer.allocateDirect(8 * 4)
        .order(ByteOrder.nativeOrder()).asFloatBuffer();
    private final float[] transform = new float[16];
    private volatile boolean stopped, broken;
    private volatile int frames;
    private volatile float strength, aspect = 4f / 3f;
    private boolean created, hasFrame;
    private SurfaceTexture texture;
    private Surface output;
    private int textureId, program, position, matrix, warp, imageAspect, sampler;
    private static final String VERTEX =
        "attribute vec2 aPosition; varying vec2 uv; void main(){" +
        "gl_Position=vec4(aPosition,0.0,1.0); uv=(aPosition+1.0)*0.5;}";
    private static final String FRAGMENT =
        "#extension GL_OES_EGL_image_external : require\n" +
        "precision highp float; uniform samplerExternalOES camera;" +
        "uniform mat4 texMatrix; uniform float strength; uniform float aspect; varying vec2 uv;" +
        "void main(){ vec2 p=(uv*2.0-1.0)*vec2(1.0,1.0/aspect);" +
        "float t=length(p)*strength; float s=t<0.00001?1.0:atan(t)/t;" +
        "vec2 source=vec2(p.x,p.y*aspect)*s*0.5+0.5;" +
        "vec2 coord=(texMatrix*vec4(source,0.0,1.0)).xy;" +
        "gl_FragColor=texture2D(camera,coord);}";

    public DewarpView(Context context, int mode, Listener listener) {
        super(context); this.listener = listener; strength = DewarpModel.strength(mode);
        vertices.put(new float[]{-1,-1, 1,-1, -1,1, 1,1}).position(0);
        setEGLContextClientVersion(2);
        setEGLConfigChooser(8, 8, 8, 0, 0, 0);
        setPreserveEGLContextOnPause(false);
        setRenderer(this); setRenderMode(RENDERMODE_WHEN_DIRTY);
    }
    public static int readMode(Context context) {
        return DewarpModel.valid(context.getSharedPreferences("viewer-renderer", 0).getInt("lens-mode", DewarpModel.DEFAULT_MODE));
    }
    public static void saveMode(Context context, int mode) {
        context.getSharedPreferences("viewer-renderer", 0).edit()
            .putInt("lens-mode", DewarpModel.valid(mode)).apply();
    }
    public void mode(int mode) { strength = DewarpModel.strength(mode); requestRender(); }
    public void aspect(float ratio) {
        if (ratio > 0f && !Float.isInfinite(ratio) && !Float.isNaN(ratio)) aspect = ratio;
        requestRender();
    }
    public int frames() { return frames; }
    public boolean live() { return !stopped && !broken && frames > 0; }
    private void fail() {
        if (stopped || broken) return;
        broken = true;
        main.post(new Runnable() { public void run() { if (!stopped) listener.failed(); }});
    }
    private static void check() {
        if (GLES20.glGetError() != GLES20.GL_NO_ERROR) throw new IllegalStateException();
    }
    private static int shader(int type, String source) {
        int id = GLES20.glCreateShader(type);
        GLES20.glShaderSource(id, source); GLES20.glCompileShader(id);
        int[] status = new int[1]; GLES20.glGetShaderiv(id, GLES20.GL_COMPILE_STATUS, status, 0);
        if (status[0] == 0) { GLES20.glDeleteShader(id); throw new IllegalStateException(); }
        return id;
    }
    @Override public void onSurfaceCreated(GL10 gl, EGLConfig config) {
        if (stopped || broken) return;
        // Unexpected context recreation falls back safely rather than replacing a live decoder surface.
        if (created) { fail(); return; }
        created = true;
        try {
            String extensions = GLES20.glGetString(GLES20.GL_EXTENSIONS);
            if (extensions == null || !extensions.contains("GL_OES_EGL_image_external")) throw new IllegalStateException();
            int vs = shader(GLES20.GL_VERTEX_SHADER, VERTEX), fs = 0;
            try {
                fs = shader(GLES20.GL_FRAGMENT_SHADER, FRAGMENT);
                program = GLES20.glCreateProgram(); GLES20.glAttachShader(program, vs); GLES20.glAttachShader(program, fs);
                GLES20.glLinkProgram(program);
            } finally { GLES20.glDeleteShader(vs); if (fs != 0) GLES20.glDeleteShader(fs); }
            int[] linked = new int[1]; GLES20.glGetProgramiv(program, GLES20.GL_LINK_STATUS, linked, 0);
            if (linked[0] == 0) throw new IllegalStateException();
            position = GLES20.glGetAttribLocation(program, "aPosition");
            matrix = GLES20.glGetUniformLocation(program, "texMatrix");
            warp = GLES20.glGetUniformLocation(program, "strength");
            imageAspect = GLES20.glGetUniformLocation(program, "aspect");
            sampler = GLES20.glGetUniformLocation(program, "camera");
            int[] id = new int[1]; GLES20.glGenTextures(1, id, 0); textureId = id[0];
            GLES20.glBindTexture(GLES11Ext.GL_TEXTURE_EXTERNAL_OES, textureId);
            GLES20.glTexParameteri(GLES11Ext.GL_TEXTURE_EXTERNAL_OES, GLES20.GL_TEXTURE_MIN_FILTER, GLES20.GL_LINEAR);
            GLES20.glTexParameteri(GLES11Ext.GL_TEXTURE_EXTERNAL_OES, GLES20.GL_TEXTURE_MAG_FILTER, GLES20.GL_LINEAR);
            GLES20.glTexParameteri(GLES11Ext.GL_TEXTURE_EXTERNAL_OES, GLES20.GL_TEXTURE_WRAP_S, GLES20.GL_CLAMP_TO_EDGE);
            GLES20.glTexParameteri(GLES11Ext.GL_TEXTURE_EXTERNAL_OES, GLES20.GL_TEXTURE_WRAP_T, GLES20.GL_CLAMP_TO_EDGE);
            texture = new SurfaceTexture(textureId);
            texture.setOnFrameAvailableListener(new SurfaceTexture.OnFrameAvailableListener() {
                @Override public void onFrameAvailable(SurfaceTexture ignored) {
                    if (!stopped && !broken) { framePending.set(true); requestRender(); }
                }
            });
            output = new Surface(texture); check();
            main.post(new Runnable() { public void run() { if (!stopped && !broken) listener.ready(output); }});
        } catch (RuntimeException e) { fail(); } // No GL/vendor/error strings or camera data logged.
    }
    @Override public void onSurfaceChanged(GL10 gl, int width, int height) {
        GLES20.glViewport(0, 0, width, height);
    }
    @Override public void onDrawFrame(GL10 gl) {
        if (stopped || broken) return;
        try {
            boolean fresh = framePending.getAndSet(false);
            if (fresh) { texture.updateTexImage(); texture.getTransformMatrix(transform); hasFrame = true; }
            GLES20.glClearColor(0, 0, 0, 1); GLES20.glClear(GLES20.GL_COLOR_BUFFER_BIT);
            if (!hasFrame) return;
            GLES20.glUseProgram(program);
            GLES20.glActiveTexture(GLES20.GL_TEXTURE0);
            GLES20.glBindTexture(GLES11Ext.GL_TEXTURE_EXTERNAL_OES, textureId);
            GLES20.glUniform1i(sampler, 0); GLES20.glUniform1f(warp, strength);
            GLES20.glUniform1f(imageAspect, aspect);
            GLES20.glUniformMatrix4fv(matrix, 1, false, transform, 0);
            vertices.position(0);
            GLES20.glEnableVertexAttribArray(position);
            GLES20.glVertexAttribPointer(position, 2, GLES20.GL_FLOAT, false, 0, vertices);
            GLES20.glDrawArrays(GLES20.GL_TRIANGLE_STRIP, 0, 4); check();
            if (fresh) frames++; // New source frames only; UI redraws cannot hide a frozen stream.
        } catch (RuntimeException e) { fail(); }
    }
    public void shutdown() {
        stopped = true; main.removeCallbacksAndMessages(null);
        queueEvent(new Runnable() { public void run() {
            if (output != null) { output.release(); output = null; }
            if (texture != null) { texture.setOnFrameAvailableListener(null); texture.release(); texture = null; }
            // EGL context teardown owns GL objects, including partial initialization failures.
        }});
        onPause(); // Wait for the GL thread to pause after its queued release.
    }
}
