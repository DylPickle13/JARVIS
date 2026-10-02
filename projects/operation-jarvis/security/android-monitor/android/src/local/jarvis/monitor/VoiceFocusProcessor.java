package local.jarvis.monitor;

import android.os.Debug;
import com.google.android.exoplayer2.C;
import com.google.android.exoplayer2.audio.BaseAudioProcessor;
import java.nio.ByteBuffer;

/** Bounded PCM adapter. Playback thread owns DSP; UI only writes the volatile mode.
 * Always active for supported PCM, including Original, so toggles never reconfigure RTSP/audio.
 * Unsupported formats bypass this processor unchanged. No retained PCM after flush/reset.
 */
public final class VoiceFocusProcessor extends BaseAudioProcessor {
    private volatile boolean focus;
    private volatile boolean supported;
    private volatile long samplesIn, samplesOut, cpuNanos;
    private VoiceFocus dsp;
    private ByteBuffer endOutput = EMPTY_BUFFER;
    public VoiceFocusProcessor(boolean enabled) { focus = enabled; }
    public void focus(boolean enabled) { focus = enabled; }
    public boolean supported() { return supported; }
    public long samples() { return samplesIn; }
    public long outputSamples() { return samplesOut; }
    public long cpuMicros() { return cpuNanos/1000; }
    @Override protected AudioFormat onConfigure(AudioFormat format) {
        supported = format.sampleRate == 8000 && format.channelCount == 1 && format.encoding == C.ENCODING_PCM_16BIT;
        return supported ? format : AudioFormat.NOT_SET;
    }
    @Override public void queueInput(ByteBuffer input) {
        if (!input.hasRemaining()) return;
        long started = Debug.threadCpuTimeNanos();
        // Consume at most 4096 bytes per call regardless of a decoder's buffer size.
        int count = Math.min(2048, input.remaining()/2);
        if (count == 0) throw new IllegalArgumentException("Unaligned PCM");
        ByteBuffer output = replaceOutputBuffer((count+VoiceFocus.HOP)*2);
        boolean enabled = focus;
        for (int i=0; i<count; i++) {
            // Explicit little-endian PCM, independent of the decoder buffer's byte-order flag.
            short sample = (short)((input.get()&255) | ((input.get()&255)<<8));
            if (dsp.push(sample, enabled)) emit(output, VoiceFocus.HOP);
        }
        samplesIn += count;
        output.flip(); cpuNanos += Math.max(0, Debug.threadCpuTimeNanos()-started);
    }
    private void emit(ByteBuffer output, int count) {
        for (int i=0; i<count; i++) {
            short value = dsp.output(i); output.put((byte)value); output.put((byte)(value>>8));
        }
        samplesOut += count;
    }
    @Override protected void onQueueEndOfStream() {
        if (dsp == null || samplesIn == samplesOut) return;
        // Flush the last partial block and lookahead; trim padding, preserve exact media duration.
        // EOS may arrive while the sink still holds our last returned output buffer.
        // Never reuse/overwrite it: allocate at most 512 bytes for this one stream tail.
        ByteBuffer output = ByteBuffer.allocateDirect(VoiceFocus.SIZE*2);
        for (int i=0; samplesOut<samplesIn && i<VoiceFocus.SIZE; i++) {
            if (dsp.push((short)0, focus)) emit(output, (int)Math.min(VoiceFocus.HOP, samplesIn-samplesOut));
        }
        output.flip(); endOutput = output;
    }
    @Override public ByteBuffer getOutput() {
        ByteBuffer output = super.getOutput();
        if (output.hasRemaining()) return output;
        output = endOutput; endOutput = EMPTY_BUFFER;
        return output;
    }
    @Override public boolean isEnded() { return super.isEnded() && !endOutput.hasRemaining(); }
    @Override protected void onFlush() {
        dsp = inputAudioFormat.sampleRate == 8000 && inputAudioFormat.channelCount == 1 &&
            inputAudioFormat.encoding == C.ENCODING_PCM_16BIT ? new VoiceFocus() : null;
        supported = dsp != null;
        endOutput = EMPTY_BUFFER;
        samplesIn = samplesOut = cpuNanos = 0;
    }
    @Override protected void onReset() {
        dsp = null; supported = false; endOutput = EMPTY_BUFFER; samplesIn = samplesOut = cpuNanos = 0;
    }
}
