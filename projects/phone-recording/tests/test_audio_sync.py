import json
from pathlib import Path
import tempfile
import unittest
import numpy as np
import opentimelineio as otio
from audio_sync import align, window_match, make_timeline, RATE
from export_verified_take import catalog
from prepare_resolve import verify
import hashlib


class AudioSyncTests(unittest.TestCase):
    def setUp(self):
        self.audio = np.random.default_rng(19).normal(0,.1,RATE*45).astype(np.float32)

    def test_later_camera_positive_offset(self):
        r = align(self.audio,self.audio[6000:])
        self.assertTrue(r['accepted']); self.assertAlmostEqual(r['offset_seconds'],.75,places=4)

    def test_earlier_camera_negative_offset_and_inverted_audio(self):
        r = align(self.audio[6000:],-self.audio)
        self.assertTrue(r['accepted']); self.assertAlmostEqual(r['offset_seconds'],-.75,places=4)

    def test_silence_rejected(self):
        self.assertFalse(align(self.audio,np.zeros_like(self.audio))['accepted'])

    def test_unrelated_audio_rejected(self):
        other = np.random.default_rng(91).normal(0,.1,len(self.audio)).astype(np.float32)
        self.assertFalse(align(self.audio,other)['accepted'])

    def test_repetitive_tone_rejected(self):
        tone = np.sin(np.arange(RATE*30)*2*np.pi*200/RATE)
        self.assertFalse(window_match(tone,tone,10)['accepted'])

    def test_offsets_beyond_bound_rejected(self):
        self.assertFalse(align(self.audio,self.audio[12*RATE:],max_offset=3)['accepted'])

    def test_drift_rejected(self):
        # Smooth signal survives resampling, but drifts 90ms over the take.
        from scipy.ndimage import gaussian_filter1d
        smooth = gaussian_filter1d(self.audio,8)
        target = np.interp(np.arange(len(smooth))*1.002,np.arange(len(smooth)),smooth)
        self.assertFalse(align(smooth,target)['accepted'])

    def test_microphone_eq_gain_echo_and_noise(self):
        from scipy import signal
        # A varying broadband source, heard through a different mic/room path.
        rng = np.random.default_rng(73)
        envelope = np.interp(np.arange(len(self.audio)),np.linspace(0,len(self.audio)-1,150),rng.uniform(.05,1,150))
        source = self.audio*envelope
        colored = signal.sosfiltfilt(signal.butter(2,[350,2200],fs=RATE,btype='bandpass',output='sos'),source)
        colored += .25*np.r_[np.zeros(120),colored[:-120]]
        colored *= np.linspace(.4,2,len(colored))
        colored += rng.normal(0,.001,len(colored))
        r = align(source,colored[3000:])
        self.assertTrue(r['accepted'],r)
        self.assertAlmostEqual(r['offset_seconds'],.375,delta=.01)

    def test_repeated_audio_loop_rejected(self):
        loop = np.tile(self.audio[:RATE*4],12)
        self.assertFalse(align(loop,loop[RATE:])['accepted'])

    def test_missing_audio_chunk_rejected(self):
        target = np.r_[self.audio[:RATE*22],self.audio[RATE*22+1600:]]
        self.assertFalse(align(self.audio,target)['accepted'])

    def test_nonfinite_audio_rejected(self):
        bad = self.audio.copy(); bad[200] = np.nan
        with self.assertRaises(ValueError): align(self.audio,bad)

    def test_otio_tracks_offsets_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            clips = [{'role':role,'path':str(Path(d)/(role+'.mp4')),'metadata':{'format':{'duration':'30'}}} for role in ('a','b')]
            p=Path(d)/'sync.otio'; make_timeline(clips,{'a':-.5,'b':.25},p,'test')
            result=otio.adapters.read_from_file(str(p))
            self.assertEqual(len(result.tracks),4)
            self.assertEqual(clips[0]['timeline_start_frame'],0)
            self.assertEqual(clips[1]['timeline_start_frame'],22)
            self.assertIsInstance(result.tracks[2][0],otio.schema.Gap)

    def test_local_checksum_conflict(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d); (p/'x.mp4').write_bytes(b'original')
            info={'files':{'x.mp4':{'bytes':8,'sha256':hashlib.sha256(b'original').hexdigest()}}}
            verify(p,info)
            (p/'x.mp4').write_bytes(b'modified')
            with self.assertRaises(RuntimeError): verify(p,info)

    def test_catalog_excludes_unverified_media(self):
        with tempfile.TemporaryDirectory() as d:
            folder=Path(d)/'test'; (folder/'iphone').mkdir(parents=True)
            (folder/'transfer-manifest.json').write_text(json.dumps({'id':'test','files':{}}))
            (folder/'iphone/x.mov').write_bytes(b'unverified')
            with self.assertRaises(RuntimeError): catalog(Path(d),'test')


if __name__ == '__main__': unittest.main()
