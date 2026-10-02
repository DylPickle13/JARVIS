"""Remote idle-only Android and iPhone screen snapshots. No stream or camera toggle."""
import base64
import datetime
import fcntl
from pathlib import Path
import subprocess
import tempfile
import managed_control as pair
from camera_config import CONFIG_ID,PREVIEW_ROLES,CAMERAS
from iphone_preview import capture as iphone_snapshot


def capture():
    with (pair.ROOT/'.pair-control.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        if (pair.ROOT/'pending-take.json').exists():
            raise RuntimeError('Framing unavailable while a managed take is pending')
        if pair.status()!=pair.IDLE:
            raise RuntimeError('Every enabled camera must be verified idle for framing snapshots')
        images={}
        with tempfile.TemporaryDirectory(prefix='phone-framing-') as temp:
            for role in PREVIEW_ROLES:
                if CAMERAS[role]['platform']=='iphone':
                    png=iphone_snapshot()
                else:
                    serial=pair.PHONES[role]
                    png=subprocess.check_output([pair.DEFAULT_ADB,'-s',serial,'exec-out','screencap','-p'],timeout=15)
                if not png.startswith(b'\x89PNG\r\n\x1a\n') or len(png)>30_000_000:
                    raise RuntimeError('Invalid screenshot')
                source=Path(temp)/(role+'.png');target=Path(temp)/(role+'.jpg');source.write_bytes(png)
                subprocess.run(['/usr/bin/sips','-Z','960','-s','format','jpeg','-s','formatOptions','65',str(source),'--out',str(target)],check=True,capture_output=True,timeout=15)
                data=target.read_bytes()
                if not data.startswith(b'\xff\xd8') or len(data)>1_000_000:raise RuntimeError('Snapshot too large')
                images[role]=base64.b64encode(data).decode('ascii')
        after=pair.status()
        if after!=pair.IDLE:
            raise RuntimeError('Camera state changed; snapshots discarded')
        return {'config_id':CONFIG_ID,'observed':datetime.datetime.now().astimezone().isoformat(),'images':images,'states':after}
