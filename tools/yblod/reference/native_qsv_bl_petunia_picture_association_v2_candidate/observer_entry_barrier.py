"""Fresh nonce barrier before running the unchanged reviewed observer."""
import json
import os
from pathlib import Path
import runpy
import stat
import sys
import time

nonce,ready,ack,observer=sys.argv[1:5]
assert len(nonce)==64 and all(c in '0123456789abcdef' for c in nonce)
ready,ack=Path(ready),Path(ack)
assert not ready.exists() and not ack.exists()
fields=Path('/proc/self/stat').read_text().rsplit(')',1)[1].split()
building=Path(str(ready)+'.building')
fd=os.open(building,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
with os.fdopen(fd,'w') as stream:
    json.dump({'pid':os.getpid(),'start_ticks':int(fields[19]),'nonce':nonce},stream)
# Publish only a complete checkpoint, without replacing another path.
os.link(building,ready)
building.unlink()
deadline=time.monotonic()+15
while not ack.exists():
    assert time.monotonic()<deadline,'Unacknowledged observer admission'
    time.sleep(.05)
fd=os.open(ack,os.O_RDONLY|os.O_NOFOLLOW)
with os.fdopen(fd,'rb') as stream:
    info=os.fstat(stream.fileno())
    assert stat.S_ISREG(info.st_mode) and stat.S_IMODE(info.st_mode)==0o600
    assert stream.read()==nonce.encode()
sys.argv=[observer]+sys.argv[5:]
runpy.run_path(observer,run_name='__main__')
