package local.jarvis.monitor;

import java.util.Arrays;

/** Native-rate 8 kHz mono DSP. No model, resampler, threads, I/O or per-frame allocation.
 * 256-point square-root Hann STFT, 128-sample hop; gentle 120 Hz high-pass plus
 * minimum-statistics stationary-noise attenuation, capped at 6 dB per FFT bin.
 * This is NOT a speech classifier: traffic overlapping speech can remain audible.
 * Input/output counts match after draining; analysis holds 128..255 samples (16..32 ms).
 */
public final class VoiceFocus {
    public static final int HOP = 128, SIZE = 256;
    private static final int BINS = SIZE / 2 + 1, BUCKETS = 8, BUCKET_FRAMES = 16;
    private final double[] window = new double[SIZE], cos = new double[SIZE/2], sin = new double[SIZE/2];
    private final double[] real = new double[SIZE], imag = new double[SIZE], filtered = new double[SIZE];
    private final short[] dry = new short[SIZE], result = new short[HOP];
    private final double[] overlap = new double[HOP], power = new double[BINS], gains = new double[BINS];
    private final double[][] minima = new double[BUCKETS][BINS];
    private int fill, bucket, bucketFrames, noiseFrames;
    private double x1, x2, y1, y2, mix;
    private boolean running, primed;
    // Butterworth high-pass, fs=8000 Hz, fc=120 Hz, Q=1/sqrt(2).
    private final double b0, b1, b2, a1, a2;

    public VoiceFocus() {
        double w = 2*Math.PI*120/8000, alpha = Math.sin(w)/Math.sqrt(2), d = 1+alpha;
        b0 = (1+Math.cos(w))/(2*d); b1 = -(1+Math.cos(w))/d; b2 = b0;
        a1 = -2*Math.cos(w)/d; a2 = (1-alpha)/d;
        for (int i=0; i<SIZE; i++) window[i] = Math.sin(Math.PI*i/SIZE);
        for (int i=0; i<SIZE/2; i++) { cos[i] = Math.cos(2*Math.PI*i/SIZE); sin[i] = Math.sin(2*Math.PI*i/SIZE); }
        clearNoise();
    }
    private void clearNoise() {
        Arrays.fill(power, 0); Arrays.fill(gains, 1);
        for (double[] row : minima) Arrays.fill(row, Double.POSITIVE_INFINITY);
        bucket = bucketFrames = noiseFrames = 0;
    }
    /** Returns true only when HOP output samples are available in output(). */
    public boolean push(short sample, boolean focus) {
        double x = sample, y = b0*x+b1*x1+b2*x2-a1*y1-a2*y2;
        x2=x1; x1=x; y2=y1; y1=y;
        dry[HOP+fill] = sample; filtered[HOP+fill] = y;
        if (++fill < HOP) return false;
        fill = 0;
        if (focus && !running) {
            clearNoise(); running = true;
            // Prime the previous frame's overlap at unity gain for a smooth enable.
            for (int i=0; i<HOP; i++) overlap[i] = filtered[i]*window[HOP+i]*window[HOP+i];
        }
        if (running) process();
        for (int i=0; i<HOP; i++) {
            mix = Math.max(0, Math.min(1, mix + (focus ? 1.0/512 : -1.0/512)));
            double wet = running ? real[i]*window[i]+overlap[i] : dry[i];
            double value = dry[i] + mix*(wet-dry[i]);
            result[i] = (short)Math.max(-32768, Math.min(32767, Math.round(value)));
            if (running) overlap[i] = real[HOP+i]*window[HOP+i];
        }
        if (!focus && mix == 0) running = false; // Original skips FFT/noise work after a 64 ms fade.
        System.arraycopy(dry, HOP, dry, 0, HOP);
        System.arraycopy(filtered, HOP, filtered, 0, HOP);
        if (!primed) { primed = true; return false; } // Discard the negative-time prefix.
        return true;
    }
    public short output(int index) { return result[index]; }

    private void process() {
        for (int i=0; i<SIZE; i++) { real[i] = filtered[i]*window[i]; imag[i] = 0; }
        fft(false);
        if (bucketFrames == BUCKET_FRAMES) {
            bucket = (bucket+1)%BUCKETS; bucketFrames = 0;
            Arrays.fill(minima[bucket], Double.POSITIVE_INFINITY);
        }
        for (int k=0; k<BINS; k++) {
            double p = real[k]*real[k]+imag[k]*imag[k];
            power[k] = noiseFrames == 0 ? p : .8*power[k]+.2*p;
            minima[bucket][k] = Math.min(minima[bucket][k], power[k]);
            double noise = minima[0][k];
            for (int b=1; b<BUCKETS; b++) noise = Math.min(noise, minima[b][k]);
            // ~2 s rolling minima; smooth power avoids a single quiet sample driving the floor to zero.
            // No gate, gain boost or AGC. A conservative 0.5 amplitude floor protects quiet speech.
            double target = noiseFrames < 32 ? 1 : Math.sqrt(Math.max(.25, 1-1.5*noise/(power[k]+1)));
            gains[k] += (target > gains[k] ? .6 : .15)*(target-gains[k]);
        }
        for (int k=0; k<SIZE; k++) {
            int bin = k <= SIZE/2 ? k : SIZE-k;
            double gain = (gains[Math.max(0,bin-1)]+2*gains[bin]+gains[Math.min(BINS-1,bin+1)])/4;
            real[k] *= gain; imag[k] *= gain;
        }
        noiseFrames = Math.min(1000, noiseFrames+1); bucketFrames++;
        fft(true);
    }
    private void fft(boolean inverse) {
        for (int i=1,j=0; i<SIZE; i++) {
            int bit=SIZE>>1;
            for (; (j&bit)!=0; bit>>=1) j^=bit;
            j^=bit;
            if (i<j) {
                double t=real[i]; real[i]=real[j]; real[j]=t;
                t=imag[i]; imag[i]=imag[j]; imag[j]=t;
            }
        }
        for (int length=2; length<=SIZE; length<<=1) {
            int half=length>>1, step=SIZE/length;
            for (int start=0; start<SIZE; start+=length) for (int j=0; j<half; j++) {
                int a=start+j, b=a+half, w=j*step;
                double wr=cos[w], wi=inverse ? sin[w] : -sin[w];
                double r=real[b]*wr-imag[b]*wi, im=real[b]*wi+imag[b]*wr;
                real[b]=real[a]-r; imag[b]=imag[a]-im; real[a]+=r; imag[a]+=im;
            }
        }
        if (inverse) for (int i=0; i<SIZE; i++) { real[i]/=SIZE; imag[i]/=SIZE; }
    }
}
