import local.jarvis.monitor.VoiceFocus;
import java.util.Random;

/** Synthetic DSP regression tests, not a substitute for listening to real speech/wind. */
public final class VoiceFocusTest {
    private static int checks;
    private static void check(boolean ok, String why) { checks++; if (!ok) throw new AssertionError(why); }
    private static short[] run(short[] input, boolean focus) {
        VoiceFocus dsp = new VoiceFocus(); short[] output = new short[input.length]; int written=0;
        for (int i=0; i<input.length+VoiceFocus.SIZE && written<input.length; i++) {
            if (dsp.push(i<input.length ? input[i] : 0, focus)) {
                for (int j=0; j<VoiceFocus.HOP && written<input.length; j++) output[written++]=dsp.output(j);
            }
        }
        check(written==input.length, "drain length"); return output;
    }
    private static double rms(short[] a, int from, int to) {
        double sum=0; for(int i=from;i<to;i++) sum+=(double)a[i]*a[i]; return Math.sqrt(sum/(to-from));
    }
    private static short[] tone(double hz, int n) {
        short[] a=new short[n]; for(int i=0;i<n;i++) a[i]=(short)Math.round(6000*Math.sin(2*Math.PI*hz*i/8000)); return a;
    }
    public static void main(String[] args) {
        Random random = new Random(431);
        for(int length : new int[]{0,1,2,127,128,129,255,256,257,1023,8193}) {
            short[] a=new short[length]; for(int i=0;i<length;i++) a[i]=(short)random.nextInt();
            short[] b=run(a,false); for(int i=0;i<length;i++) check(a[i]==b[i],"Original bit exact at "+i);
            check(run(a,true).length==length,"filtered length");
        }
        for(short s:run(new short[24000],true)) check(s==0,"silence must remain silence");
        short[] low=tone(40,48000), high=tone(1000,48000);
        short[] lowOut=run(low,true), highOut=run(high,true);
        double lowGain=rms(lowOut,24000,40000)/rms(low,24000,40000);
        double highGain=rms(highOut,24000,40000)/rms(high,24000,40000);
        check(lowGain<.07,"wind rumble attenuation");
        check(highGain>.47 && highGain<.6,"6dB floor for stationary speech-band tone");
        double warmGain=rms(highOut,1024,3000)/rms(high,1024,3000);
        check(warmGain>.99 && warmGain<1.01,"FFT overlap-add unity before adaptation");
        short[] noise=new short[48000]; for(int i=0;i<noise.length;i++) noise[i]=(short)(random.nextGaussian()*1400);
        short[] clean=run(noise,true); double noiseGain=rms(clean,24000,40000)/rms(noise,24000,40000);
        check(noiseGain>.35 && noiseGain<.85,"moderate stationary noise reduction");
        // Quiet history followed by an amplitude-modulated harmonic burst. No speech gate may erase onset.
        short[] burst=noise.clone();
        for(int i=24000;i<32000;i++) burst[i]+=(short)(5000*(.6+.4*Math.sin(2*Math.PI*4*i/8000))*
            (Math.sin(2*Math.PI*700*i/8000)+.3*Math.sin(2*Math.PI*1400*i/8000)));
        short[] burstOut=run(burst,true);
        double burstGain=rms(burstOut,24128,30000)/rms(burst,24128,30000);
        check(burstGain>.7,"preserve modulated speech-band burst");
        // Hard full-scale input and rapid mode changes cannot lose samples or poison later silence.
        VoiceFocus dsp=new VoiceFocus(); int count=0;
        for(int i=0;i<64000;i++) if(dsp.push(i<16000 ? (short)(i%2==0 ? 32767 : -32768) : 0,(i/512)%2==0)) {
            count+=VoiceFocus.HOP;
            if(i>60000) for(int j=0;j<VoiceFocus.HOP;j++) check(dsp.output(j)==0,"settles after overload/toggles");
        }
        check(count==64000-128,"bounded lookahead");
        System.out.printf("Gains: 40Hz=%.3f, 1kHz=%.3f, noise=%.3f, burst=%.3f%n",lowGain,highGain,noiseGain,burstGain);
        System.out.println(checks+" voice DSP assertions passed.");
    }
}
