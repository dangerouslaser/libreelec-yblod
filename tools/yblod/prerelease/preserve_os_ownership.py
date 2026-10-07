"""Recompress staged OS preserving original protected helper ownership."""
import os,pathlib,subprocess,shutil,hashlib
out=pathlib.Path('/home/bryan/Projects/libreelec-yblod-reconstruction/target/release-yblod-0.2-pre1');stem='LibreELEC-Generic.x86_64-13.0-yblod-0.2-pre1'
root=out/'rootfs';helper=root/'usr/lib/dbus/dbus-daemon-launch-helper'
assert os.geteuid()==0 and helper.stat().st_uid==0 and helper.stat().st_gid==81
assert helper.stat().st_mode & 0o7777==0o4750
system=out/(stem+'.system');system.rename(out/(stem+'.system.ownership-rejected'))
subprocess.run(['mksquashfs',str(root),str(system),'-noappend','-comp','zstd','-Xcompression-level','19','-b','1048576','-processors','4','-mem','512M','-no-xattrs'],check=True)
listing=subprocess.check_output(['unsquashfs','-ll',str(system),'usr/lib/dbus/dbus-daemon-launch-helper'],text=True)
assert 'root/81' in listing and '-rwsr-x---' in listing
target=out/stem/'target/SYSTEM';shutil.copyfile(system,target)
subprocess.run(['/usr/bin/python3','/home/bryan/Projects/libreelec-yblod-reconstruction/tools/yblod/prerelease/finish_artifacts.py'],check=True)
