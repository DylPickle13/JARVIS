import local.jarvis.monitor.VoiceFocusProcessor;
import com.google.android.exoplayer2.C;
import com.google.android.exoplayer2.audio.AudioProcessingPipeline;
import com.google.common.collect.ImmutableList;
import com.google.android.exoplayer2.audio.AudioProcessor.AudioFormat;
import java.nio.ByteBuffer;
import java.util.Random;

/** Runs with the real ExoPlayer BaseAudioProcessor on Android; synthetic PCM only, no AudioTrack. */
public final class VoiceFocusProcessorTest {
    private static int checks;
    private static void check(boolean b, String message) { checks++; if(!b) throw new AssertionError(message); }
    private static VoiceFocusProcessor create(boolean focus) throws Exception {
        VoiceFocusProcessor p=new VoiceFocusProcessor(focus);
        p.configure(new AudioFormat(8000,1,C.ENCODING_PCM_16BIT)); p.flush();
        check(p.isActive() && p.supported(),"supported PCM"); return p;
    }
    private static int drain(VoiceFocusProcessor p, short[] expected, int at, boolean compare) {
        ByteBuffer out=p.getOutput(); check(out.remaining()%2==0,"aligned output");
        check(out.capacity()<=4352,"bounded output capacity");
        while(out.hasRemaining()) {
            short value=(short)((out.get()&255)|((out.get()&255)<<8));
            check(at<expected.length,"no inserted samples");
            if(compare) check(value==expected[at],"Original bit exact");
            at++;
        }
        return at;
    }
    private static void stream(short[] samples, int chunk, boolean focus) throws Exception {
        VoiceFocusProcessor p=create(focus); int written=0;
        for(int start=0;start<samples.length;start+=chunk) {
            int n=Math.min(chunk,samples.length-start);
            ByteBuffer in=ByteBuffer.allocate(n*2+6); in.position(3);
            for(int i=0;i<n;i++) { short v=samples[start+i]; in.put((byte)v); in.put((byte)(v>>8)); }
            in.flip(); in.position(3); // Nonzero position, deliberately default BIG_ENDIAN flag.
            while(in.hasRemaining()) {
                p.queueInput(in); written=drain(p,samples,written,!focus);
                check(p.samples()-p.outputSamples()<=255,"bounded lookahead");
            }
        }
        p.queueEndOfStream(); written=drain(p,samples,written,!focus);
        check(written==samples.length && p.samples()==p.outputSamples(),"EOS preserves exact duration");
        check(p.isEnded(),"EOS drained"); p.reset();
        check(!p.supported() && p.samples()==0 && p.outputSamples()==0,"reset releases DSP/telemetry");
    }
    private static void pipelineTail() throws Exception {
        VoiceFocusProcessor p = new VoiceFocusProcessor(false);
        AudioProcessingPipeline pipe = new AudioProcessingPipeline(ImmutableList.of(p));
        pipe.configure(new AudioFormat(8000,1,C.ENCODING_PCM_16BIT)); pipe.flush();
        ByteBuffer in = ByteBuffer.allocateDirect(512);
        for(int i=0;i<256;i++) { in.put((byte)i); in.put((byte)(i>>8)); } in.flip();
        pipe.queueInput(in);
        ByteBuffer outstanding = pipe.getOutput();
        check(outstanding.hasRemaining(),"pipeline output before EOS");
        int at=0;
        // Partially consume, then EOS while downstream still holds the returned PCM.
        for(;at<7;at++) check((short)((outstanding.get()&255)|((outstanding.get()&255)<<8))==at,"prefix");
        pipe.queueEndOfStream();
        while(outstanding.hasRemaining()) {
            check((short)((outstanding.get()&255)|((outstanding.get()&255)<<8))==at++,"EOS must not overwrite outstanding PCM");
        }
        for(int attempt=0; !pipe.isEnded() && attempt<10; attempt++) {
            ByteBuffer tail=pipe.getOutput();
            while(tail.hasRemaining()) check((short)((tail.get()&255)|((tail.get()&255)<<8))==at++,"ordered tail");
        }
        check(pipe.isEnded() && at==256,"backpressured pipeline duration"); pipe.reset();
    }
    public static void main(String[] args) throws Exception {
        pipelineTail();
        Random random=new Random(421);
        for(int n:new int[]{0,1,127,128,129,255,256,257,4097,12000}) {
            short[] samples=new short[n]; for(int i=0;i<n;i++) samples[i]=(short)random.nextInt();
            for(int chunk:new int[]{1,79,128,160,4096}) for(boolean focus:new boolean[]{false,true}) stream(samples,chunk,focus);
        }
        VoiceFocusProcessor p=create(true);
        ByteBuffer data=ByteBuffer.allocate(1024); while(data.hasRemaining()) data.put((byte)63); data.flip();
        p.queueInput(data); p.getOutput(); p.flush();
        check(p.samples()==0 && p.outputSamples()==0,"flush drops retained audio");
        p.focus(false); p.queueInput(ByteBuffer.allocate(512));
        ByteBuffer silence=p.getOutput(); while(silence.hasRemaining()) check(silence.get()==0,"flush removed prior PCM");
        p.reset();
        for(AudioFormat format:new AudioFormat[]{new AudioFormat(16000,1,C.ENCODING_PCM_16BIT),
                new AudioFormat(8000,2,C.ENCODING_PCM_16BIT),new AudioFormat(8000,1,C.ENCODING_PCM_FLOAT)}) {
            check(p.configure(format)==AudioFormat.NOT_SET,"unsupported format bypass"); p.flush();
            check(!p.isActive() && !p.supported(),"no unsupported DSP"); p.reset();
        }
        for(boolean focus:new boolean[]{false,true}) {
            p=create(focus); ByteBuffer input=ByteBuffer.allocateDirect(320);
            for(int i=0;i<160;i++) { short v=(short)random.nextInt(); input.put((byte)v);input.put((byte)(v>>8)); }
            // 5 seconds warmup, then 20 seconds simulated PCM; runs offline, never played or saved.
            for(int i=0;i<250;i++) { input.rewind(); p.queueInput(input); ByteBuffer out=p.getOutput(); out.position(out.limit()); }
            long before=p.cpuMicros();
            for(int i=0;i<1000;i++) { input.rewind(); p.queueInput(input); ByteBuffer out=p.getOutput(); out.position(out.limit()); }
            long cost=p.cpuMicros()-before;
            System.out.println("Synthetic native-rate "+(focus?"Voice focus":"Original")+": "+cost+" CPU us / 20 audio seconds");
            check(cost<2000000,"DSP below conservative 10% single-core real-time budget"); p.reset();
        }
        System.out.println(checks+" on-device voice processor assertions passed.");
    }
}
