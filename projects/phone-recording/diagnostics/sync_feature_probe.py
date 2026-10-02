"""Development-only local feature comparison; no media writes or edits."""

# Permit direct execution from the diagnostics directory.
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parents[1]))
import numpy as np
from scipy import signal
from pathlib import Path
from audio_sync import audio,probe,RATE


def features(x):
    f,t,z=signal.stft(x,fs=RATE,nperseg=256,noverlap=216,boundary=None,padded=False)
    power=np.abs(z)**2
    bands=[]
    for lo,hi in zip([180,300,450,650,950,1350,1900,2600],[300,450,650,950,1350,1900,2600,3200]):
        energy=np.mean(power[(f>=lo)&(f<hi)],axis=0)
        log=np.log(np.maximum(energy,np.max(energy)*1e-7+1e-20))
        # Remove static spectral signature/slow AGC, preserve temporal detail.
        log=signal.sosfiltfilt(signal.butter(2,1,fs=200,btype='highpass',output='sos'),log)
        bands.append(log/(np.std(log)+1e-8))
    return np.array(bands)


def match(x,y,start,seconds=8,max_offset=20,rate=200):
    t=int(start*rate);n=int(seconds*rate)
    left=max(0,t-int(max_offset*rate)); right=min(x.shape[1],t+n+int(max_offset*rate))
    a=x[:,left:right].astype(float); b=y[:,t:t+n].astype(float)
    if b.shape[1]!=n or a.shape[1]<n:return {}
    b-=b.mean(axis=1,keepdims=True)
    numerator=sum(signal.correlate(v,w,mode='valid',method='fft') for v,w in zip(a,b))
    sums=np.pad(np.cumsum(a,axis=1),((0,0),(1,0)));squares=np.pad(np.cumsum(a*a,axis=1),((0,0),(1,0)))
    variance=np.maximum(squares[:,n:]-squares[:,:-n]-(sums[:,n:]-sums[:,:-n])**2/n,0).sum(axis=0)
    scores=numerator/np.sqrt(np.maximum(variance*np.sum(b*b),1e-24))
    peak=int(np.argmax(scores)); best=float(scores[peak]);competitors=scores.copy();competitors[max(0,peak-20):peak+21]=0
    return {'t':start,'offset':(left+peak-t)/rate,'score':best,'ratio':best/max(float(competitors.max()),1e-9)}


if __name__=='__main__':
 root=Path.home()/'Movies/Phone Recordings/20260907-190450-df439752'
 clips={role:next((root/role).glob('*'+ext)) for role,ext in [('lg','.mp4'),('samsung','.mp4'),('iphone','.mov')]}
 arrays={role:features(audio(p,probe(p))[0]) for role,p in clips.items()}
 for ref,role in [('samsung','lg'),('samsung','iphone'),('iphone','lg')]:
  print(ref,role)
  for t in np.linspace(1,64,9): print(match(arrays[ref],arrays[role],float(t)))
