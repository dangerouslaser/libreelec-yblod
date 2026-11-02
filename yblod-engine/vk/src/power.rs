//! The GPU's clocks while Dolby Vision frames are composed (AMD).
//!
//! amdgpu's automatic power management judges the load by how busy the GPU
//! is, and the engine's work comes in short bursts a frame apart, so it keeps
//! the shader clock in its lowest states: on ryzen-fella (Vega 8) 200-435 MHz
//! of 1200 during playback. 1917 (FEL, 24p) took 22.7 ms a frame there (p95
//! 30.9) against 9.6 ms with the COMPUTE power profile, as fast as the clock
//! forced high; Gemini Man (60p MEL) 8.7 against 6.3 (2026-10-29,
//! dvvk-bench at the films' rates).
//!
//! So while frames come: the COMPUTE profile (power_dpm_force_performance_level
//! "manual", pp_power_profile_mode COMPUTE), only when the level was "auto"
//! (a setting someone made is left alone); back to "auto" (which restores
//! the default profile) a few seconds after the last frame, and when the
//! engine goes. The files are root's: big-fella's udev rule lets the video
//! group write them; without that (or another driver) nothing happens.
//! DVVK_GPU_BOOST=0: never.
//!
//! The manual level outlives the process, so "auto" is put back on every way
//! out that runs code: the idle thread, Drop, an atexit hook (a process that
//! exits without destroying the engine) and device.rs's fail-stop _exit
//! (restore_now). Only a kill or an abort leaves it manual.

use std::fs;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex, MutexGuard};
use std::time::{Duration, Instant};

const IDLE: Duration = Duration::from_secs(3);

struct State {
    active: bool,
    last: Instant,
    // A level someone else set, when it was last read: read again only
    // after IDLE (frame() runs for every frame).
    foreign: Option<Instant>,
}

pub struct Boost {
    dir: PathBuf,
    profile: String,
    state: Arc<Mutex<State>>,
    stop: Arc<AtomicBool>,
    thread: Option<std::thread::JoinHandle<()>>,
}

/// The amdgpu device behind a DRM fd (card or render node), if its power
/// files are there.
fn amdgpu_dir(drm_fd: i32) -> Option<PathBuf> {
    let mut st: libc::stat = unsafe { std::mem::zeroed() };
    if unsafe { libc::fstat(drm_fd, &mut st) } != 0 {
        return None;
    }
    let (major, minor) = (libc::major(st.st_rdev), libc::minor(st.st_rdev));
    let dir = PathBuf::from(format!("/sys/dev/char/{major}:{minor}/device"));
    let driver = fs::read_link(dir.join("driver")).ok()?;
    if driver.file_name()? != "amdgpu" {
        return None;
    }
    let ok = dir.join("power_dpm_force_performance_level").exists() && dir.join("pp_power_profile_mode").exists();
    ok.then_some(dir)
}

/// pp_power_profile_mode's number for COMPUTE ("  5        COMPUTE :  ...").
fn compute_profile(dir: &Path) -> Option<String> {
    let modes = fs::read_to_string(dir.join("pp_power_profile_mode")).ok()?;
    modes.lines().find_map(|l| {
        let mut words = l.split_whitespace();
        let n = words.next()?;
        let name = words.next()?.trim_end_matches([':', '*']);
        (name == "COMPUTE" && n.parse::<u32>().is_ok()).then(|| n.to_owned())
    })
}

fn level(dir: &Path) -> String {
    fs::read_to_string(dir.join("power_dpm_force_performance_level")).map(|s| s.trim().to_owned()).unwrap_or_default()
}

fn restore(dir: &Path) {
    if let Err(e) = fs::write(dir.join("power_dpm_force_performance_level"), "auto") {
        eprintln!("dvvk: GPU power level back to auto failed: {e}");
    }
}

/// A panic elsewhere never stops the restore: the data is plain values.
fn lock<T>(m: &Mutex<T>) -> MutexGuard<'_, T> {
    m.lock().unwrap_or_else(|poisoned| poisoned.into_inner())
}

/// The devices whose level this process set to manual and hasn't put back.
static BOOSTED: Mutex<Vec<PathBuf>> = Mutex::new(Vec::new());
static ATEXIT: std::sync::Once = std::sync::Once::new();

extern "C" fn restore_at_exit() {
    restore_now();
}

fn boosted(dir: &PathBuf, on: bool) {
    let mut b = lock(&BOOSTED);
    b.retain(|d| d != dir);
    if on {
        b.push(dir.clone());
        ATEXIT.call_once(|| unsafe {
            libc::atexit(restore_at_exit);
        });
    }
}

/// Every boosted device back to "auto" now (exit paths; idempotent). Never
/// blocks on a lock another thread holds: a held lock is skipped.
pub fn restore_now() {
    let dirs = match BOOSTED.try_lock() {
        Ok(mut b) => std::mem::take(&mut *b),
        Err(std::sync::TryLockError::Poisoned(p)) => std::mem::take(&mut *p.into_inner()),
        Err(std::sync::TryLockError::WouldBlock) => return,
    };
    for dir in &dirs {
        restore(dir);
    }
}

impl Boost {
    pub fn new(drm_fd: i32, enabled: bool) -> Option<Boost> {
        if !enabled {
            return None;
        }
        let dir = amdgpu_dir(drm_fd)?;
        let profile = compute_profile(&dir)?;
        let writable = |f: &str| fs::OpenOptions::new().write(true).open(dir.join(f)).is_ok();
        if !writable("power_dpm_force_performance_level") || !writable("pp_power_profile_mode") {
            return None;
        }
        let state = Arc::new(Mutex::new(State { active: false, last: Instant::now(), foreign: None }));
        let stop = Arc::new(AtomicBool::new(false));
        let thread = {
            let (state, stop, dir) = (state.clone(), stop.clone(), dir.clone());
            std::thread::Builder::new()
                .name("dvvk-power".into())
                .spawn(move || {
                    while !stop.load(Ordering::Relaxed) {
                        std::thread::sleep(Duration::from_millis(500));
                        let mut s = lock(&state);
                        if s.active && s.last.elapsed() >= IDLE {
                            restore(&dir);
                            boosted(&dir, false);
                            s.active = false;
                        }
                    }
                })
                .ok()?
        };
        Some(Boost { dir, profile, state, stop, thread: Some(thread) })
    }

    /// A frame is being composed.
    pub fn frame(&self) {
        let mut s = lock(&self.state);
        s.last = Instant::now();
        if s.active {
            return;
        }
        // Only from "auto": a level someone set stays theirs.
        if s.foreign.is_some_and(|t| t.elapsed() < IDLE) {
            return;
        }
        if level(&self.dir) != "auto" {
            s.foreign = Some(Instant::now());
            return;
        }
        s.foreign = None;
        let set = fs::write(self.dir.join("power_dpm_force_performance_level"), "manual")
            .and_then(|_| fs::write(self.dir.join("pp_power_profile_mode"), &self.profile));
        match set {
            Ok(()) => {
                s.active = true;
                boosted(&self.dir, true);
            }
            Err(e) => {
                eprintln!("dvvk: GPU COMPUTE power profile failed: {e}");
                restore(&self.dir);
            }
        }
    }
}

impl Drop for Boost {
    fn drop(&mut self) {
        self.stop.store(true, Ordering::Relaxed);
        if let Some(t) = self.thread.take() {
            let _ = t.join();
        }
        if lock(&self.state).active {
            restore(&self.dir);
            boosted(&self.dir, false);
        }
    }
}
