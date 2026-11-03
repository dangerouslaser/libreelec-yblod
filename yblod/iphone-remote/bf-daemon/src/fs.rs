//! Files written whole: readers see the old one or the new one, never half,
//! and after a crash the new one is either all there or not at all.

use std::io::{self, Write};
use std::os::unix::fs::{OpenOptionsExt, PermissionsExt};
use std::path::{Path, PathBuf};

/// Writes `data` to `path` through `path`.tmp: with `mode` from the start
/// (and again after, whatever the umask), synced, renamed over `path`, and
/// the folder synced. The folder must exist.
pub fn atomic_write(path: &Path, data: &[u8], mode: u32) -> io::Result<()> {
    let mut tmp = path.as_os_str().to_owned();
    tmp.push(".tmp");
    let tmp = PathBuf::from(tmp);
    let mut f = std::fs::OpenOptions::new().write(true).create(true).truncate(true).mode(mode).open(&tmp)?;
    f.set_permissions(std::fs::Permissions::from_mode(mode))?;
    f.write_all(data)?;
    f.sync_all()?;
    drop(f);
    std::fs::rename(&tmp, path)?;
    // The rename itself, on disk (best effort: not every file system lets a
    // folder be opened and synced).
    if let Some(dir) = path.parent().filter(|d| !d.as_os_str().is_empty())
        && let Ok(dir) = std::fs::File::open(dir)
    {
        let _ = dir.sync_all();
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn writes_whole_with_its_mode() {
        let dir = std::env::temp_dir().join(format!("bf-daemon-fs-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).unwrap();
        let path = dir.join("a.json");
        atomic_write(&path, b"one", 0o600).unwrap();
        atomic_write(&path, b"two", 0o644).unwrap();
        assert_eq!(std::fs::read(&path).unwrap(), b"two");
        assert_eq!(std::fs::metadata(&path).unwrap().permissions().mode() & 0o777, 0o644);
        assert!(!dir.join("a.json.tmp").exists());
        atomic_write(&path, b"three", 0o600).unwrap();
        assert_eq!(std::fs::metadata(&path).unwrap().permissions().mode() & 0o777, 0o600);
        assert!(atomic_write(&dir.join("missing").join("x"), b"", 0o600).is_err());
        std::fs::remove_dir_all(&dir).unwrap();
    }
}
