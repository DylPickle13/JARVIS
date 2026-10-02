"""Microphone-tolerant alignment using normalized multi-band audio envelopes.

No generated cues, speech recognition, network services, or timecode assumptions.
Scores are correlations, NOT probabilities. Refuse ambiguous/unstable evidence.
"""
import math
import numpy as np
from scipy import signal

RATE = 8000
FEATURE_RATE = 200
BANDS = (180,300,450,650,950,1350,1900,2600,3200)


def features(samples):
    if len(samples)<RATE*3 or not np.isfinite(samples).all():
        raise ValueError('Audio too short or nonfinite')
    f, _, z = signal.stft(samples,fs=RATE,nperseg=256,noverlap=216,boundary=None,padded=False)
    power = np.abs(z)**2
    bands = []
    highpass = signal.butter(2,1,fs=FEATURE_RATE,btype='highpass',output='sos')
    for lo,hi in zip(BANDS,BANDS[1:]):
        energy = np.mean(power[(f>=lo)&(f<hi)],axis=0)
        log = np.log(np.maximum(energy,float(np.max(energy))*1e-7+1e-20))
        log = signal.sosfiltfilt(highpass,log)
        deviation = float(np.std(log))
        # Silence/steady tones must not become strong evidence after whitening.
        useful = float(np.mean(energy))>1e-12 and deviation>.015
        bands.append(log/deviation if useful else np.zeros_like(log))
    return np.asarray(bands,dtype=np.float32)


def match(reference,target,start,seconds=8,max_offset=20):
    rate = FEATURE_RATE
    t = int(start*rate); n = int(seconds*rate)
    left = max(0,t-int(max_offset*rate)); right = min(reference.shape[1],t+n+int(max_offset*rate))
    x = reference[:,left:right].astype(np.float64)
    y = target[:,t:t+n].astype(np.float64)
    result = {'accepted':False,'target_seconds':start+seconds/2}
    if y.shape[1]!=n or x.shape[1]<n:
        return {**result,'reason':'insufficient overlap'}
    active = (np.std(x,axis=1)>.05)&(np.std(y,axis=1)>.05)
    if int(active.sum())<3:
        return {**result,'reason':'fewer than three varying frequency bands'}
    x = x[active]; y = y[active]; y -= y.mean(axis=1,keepdims=True)
    numerator = sum(signal.correlate(a,b,mode='valid',method='fft') for a,b in zip(x,y))
    sums = np.pad(np.cumsum(x,axis=1),((0,0),(1,0)))
    squares = np.pad(np.cumsum(x*x,axis=1),((0,0),(1,0)))
    variance = np.maximum(squares[:,n:]-squares[:,:-n]-(sums[:,n:]-sums[:,:-n])**2/n,0).sum(axis=0)
    scores = numerator/np.sqrt(np.maximum(variance*np.sum(y*y),1e-24))
    peak = int(np.argmax(scores)); best = float(scores[peak])
    competitors = scores.copy(); exclusion = int(.1*rate)
    competitors[max(0,peak-exclusion):peak+exclusion+1] = 0
    second = float(competitors.max(initial=0)); ratio = best/max(second,1e-9)
    # Fixed general gates: no take-specific offsets or relaxed raw-waveform gates.
    result.update(accepted=best>=.35 and ratio>=1.5,offset_seconds=(left+peak-t)/rate,
                  correlation=best,peak_ratio=ratio,active_bands=int(active.sum()))
    return result


def align_features(reference,target,max_offset=20):
    duration = min(reference.shape[1],target.shape[1])/FEATURE_RATE
    seconds = min(8,(duration-2)/3)
    result = {'accepted':False,'method':'multiband_log_envelope_v2','resolution_seconds':1/FEATURE_RATE}
    if seconds<3 or max_offset<=0 or not math.isfinite(max_offset):
        return {**result,'reason':'Insufficient duration or invalid search bound','windows':[]}
    starts = np.linspace(1,duration-seconds-1,min(25,max(9,math.ceil(duration/120))))
    windows = [match(reference,target,float(t),seconds,max_offset) for t in starts]
    good = [w for w in windows if w['accepted']]
    # Require strictly >75% of ALL sampled windows, not a cherry-picked subset.
    # Permit a weak opening/ending window, but retain distributed evidence.
    required = max(5,math.floor(len(windows)*.75)+1)
    result.update(windows=windows,accepted_windows=len(good),total_windows=len(windows),
                  required_windows=required,matched_fraction=len(good)/len(windows),
                  coverage_policy='More than 75%; first/last quarters and middle half; >=50% span',
                  reason='Too few confident matches: require more than 75% of sampled windows')
    if len(good)<required:
        return result
    times = np.array([w['target_seconds'] for w in good])
    if (times[0]>duration*.25 or times[-1]<duration*.75
            or not np.any((times>=duration*.25)&(times<=duration*.75))
            or times[-1]-times[0]<max(2*seconds,duration*.5)):
        result['reason'] = 'Confident matches do not cover beginning, middle and end sufficiently'
        return result
    offsets = np.array([w['offset_seconds'] for w in good])
    slope,intercept = np.polyfit(times,offsets,1)
    residual = float(np.max(np.abs(offsets-(intercept+slope*times))))
    spread = float(np.ptp(offsets)); drift = float(slope*duration)
    result.update(offset_seconds=float(np.median(offsets)),drift_seconds_over_take=drift,
                  residual_seconds=residual,offset_spread_seconds=spread,
                  checked_span_seconds=float(times[-1]-times[0]))
    result['accepted'] = abs(drift)<=1/30 and spread<=1/30 and residual<=.5/30
    result['reason'] = 'Distributed spectral matches agree within one frame' if result['accepted'] else 'Drift/inconsistent matches; no automatic retiming'
    return result
