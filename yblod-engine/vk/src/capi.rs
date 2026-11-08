//! The C API (include/dv_engine_vk.h).
//!
//! Every entry point checks its pointers and runs inside `catch_unwind`: a
//! panic never crosses into C. It is logged, the call returns an error, and
//! an engine that panicked is poisoned (submit fails until it is recreated),
//! since its state may be half-updated.

use crate::engine::{Engine, FrameIn};
use crate::plan::PlanIn;
use std::os::raw::c_void;
use std::panic::{catch_unwind, AssertUnwindSafe};

#[repr(C)]
pub struct DvvkFrame {
    pub plan: PlanIn,
    pub bl_surface: u32,
    pub el_surface: u32,
    pub metadata: *const u8,
    pub metadata_size: usize,
    pub output: u32,
    pub flags: u32, // DVVK_FRAME_AUTO_OVERLAY, DVVK_FRAME_DESKTOP
    pub release_wait: u64,
}

const DVVK_INVALID: i32 = -1;
const DVVK_UNSUPPORTED: i32 = -2;
const DVVK_BACKEND: i32 = -8;

fn log_error(what: &str, e: impl std::fmt::Display) {
    eprintln!("dv-engine-vk: {what}: {e}");
}

fn panic_message(p: &(dyn std::any::Any + Send)) -> &str {
    p.downcast_ref::<&str>().copied().or_else(|| p.downcast_ref::<String>().map(|s| s.as_str())).unwrap_or("?")
}

/// `f` with panics caught: `on_panic` instead.
fn guarded<T>(what: &str, on_panic: T, f: impl FnOnce() -> T) -> T {
    match catch_unwind(AssertUnwindSafe(f)) {
        Ok(v) => v,
        Err(p) => {
            log_error(what, format_args!("panic: {}", panic_message(&*p)));
            on_panic
        }
    }
}

/// `f` on the engine behind `e` (`on_null` for NULL), panics caught: the
/// engine is poisoned and `on_panic` returned.
unsafe fn with_engine<T>(e: *mut Engine, what: &str, on_null: T, on_panic: T, f: impl FnOnce(&mut Engine) -> T) -> T {
    let Some(engine) = e.as_mut() else {
        log_error(what, "NULL engine");
        return on_null;
    };
    match catch_unwind(AssertUnwindSafe(|| f(&mut *engine))) {
        Ok(v) => v,
        Err(p) => {
            log_error(what, format_args!("panic: {}", panic_message(&*p)));
            let _ = catch_unwind(AssertUnwindSafe(|| (*e).poison()));
            on_panic
        }
    }
}

/// A slice from a C pointer and length: empty for length 0 (any pointer),
/// None for NULL with a length.
unsafe fn slice<'a, T>(p: *const T, n: usize) -> Option<&'a [T]> {
    if n == 0 {
        Some(&[])
    } else if p.is_null() || n.checked_mul(std::mem::size_of::<T>()).is_none_or(|b| b > isize::MAX as usize) {
        None
    } else {
        Some(std::slice::from_raw_parts(p, n))
    }
}

/// # Safety
/// `out` must be valid; `va_display` a VADisplay on the same device as `drm_fd`.
#[no_mangle]
pub unsafe extern "C" fn dvvk_create(drm_fd: i32, va_display: *mut c_void, out: *mut *mut Engine) -> i32 {
    if out.is_null() {
        return DVVK_INVALID;
    }
    *out = std::ptr::null_mut();
    guarded("create", DVVK_BACKEND, || match Engine::new(drm_fd, va_display) {
        Ok(e) => {
            *out = Box::into_raw(Box::new(e));
            0
        }
        Err(e) => {
            log_error("create", e);
            DVVK_BACKEND
        }
    })
}

/// # Safety
/// `e` from dvvk_create; `fd` a linear XRGB8888 3840x2160 dmabuf (dup'd).
#[no_mangle]
pub unsafe extern "C" fn dvvk_set_output(e: *mut Engine, slot: u32, fd: i32, stride: u32) -> i32 {
    with_engine(e, "output", DVVK_INVALID, DVVK_BACKEND, |e| match e.set_output(slot, fd, stride) {
        Ok(()) => 0,
        Err(err) => {
            log_error("output", err);
            DVVK_BACKEND
        }
    })
}

fn frame_in(f: &DvvkFrame) -> Option<FrameIn<'_>> {
    Some(FrameIn {
        plan: f.plan,
        bl_surface: f.bl_surface,
        el_surface: f.el_surface,
        metadata: unsafe { slice(f.metadata, f.metadata_size) }?,
        output: f.output,
        auto_overlay: f.flags & 1 != 0,
        desktop: f.flags & 2 != 0,
        release_wait: f.release_wait,
    })
}

/// # Safety
/// `e` from dvvk_create; `frame` and its metadata valid for the call.
#[no_mangle]
pub unsafe extern "C" fn dvvk_render_sync(e: *mut Engine, frame: *const DvvkFrame, error_flags: *mut u32) -> i32 {
    with_engine(e, "render", DVVK_INVALID, DVVK_BACKEND, |e| {
        let Some(f) = frame.as_ref().and_then(frame_in) else { return DVVK_INVALID };
        let r = match e.render(&f) {
            Ok(s) => s,
            Err(err) => {
                log_error("render", err);
                DVVK_BACKEND
            }
        };
        if !error_flags.is_null() {
            *error_flags = e.last_error_flags;
        }
        r
    })
}

/// linux-drm-syncobj-v1: DRM syncobj fds of the frames' timeline (acquire
/// point = ticket) and of a release timeline (the caller's release points;
/// pass the one a buffer was last committed with as release_wait). The
/// caller owns both fds.
/// # Safety
/// `e` from dvvk_create; out pointers writable.
#[no_mangle]
pub unsafe extern "C" fn dvvk_timelines(e: *mut Engine, acquire: *mut i32, release: *mut i32) -> i32 {
    if acquire.is_null() || release.is_null() {
        return DVVK_INVALID;
    }
    with_engine(e, "timelines", DVVK_INVALID, DVVK_BACKEND, |e| match e.timelines() {
        Ok((a, r)) => {
            *acquire = a;
            *release = r;
            0
        }
        Err(err) => {
            log_error("timelines", err);
            DVVK_BACKEND
        }
    })
}

/// mpv's subtitle / OSD bitmaps for the following frames (0 parts: none);
/// the bitmaps are copied before this returns.
/// # Safety
/// `e` from dvvk_create; `parts` (and their bitmaps) valid for the call.
#[no_mangle]
pub unsafe extern "C" fn dvvk_set_subtitles(e: *mut Engine, parts: *const crate::overlay::SubPart, num: u32) -> i32 {
    with_engine(e, "subtitles", DVVK_INVALID, DVVK_UNSUPPORTED, |e| {
        let Some(parts) = slice(parts, num as usize) else { return DVVK_INVALID };
        match e.set_subtitles(parts) {
            Ok(()) => 0,
            Err(err) => {
                log_error("subtitles", err);
                DVVK_UNSUPPORTED
            }
        }
    })
}

/// The shell's OSD buffer (KWin's forwarded overlay) for the following
/// frames; NULL: none. The engine dups what it keeps; the caller keeps the
/// buffer itself until dvvk_overlay_ticket(id)'s frame is done. Each frame
/// that reads the buffer leaves its fence on it as an implicit read fence.
/// # Safety
/// `e` from dvvk_create; `buf` NULL or valid for the call.
#[no_mangle]
pub unsafe extern "C" fn dvvk_set_overlay(e: *mut Engine, buf: *const crate::overlay::Dmabuf, id: u64) -> i32 {
    dvvk_set_overlay_ex(e, buf, id, 0)
}

const DVVK_OVERLAY_FLIP_Y: u32 = 1;

/// dvvk_set_overlay with flags: DVVK_OVERLAY_FLIP_Y (1), the buffer's rows
/// bottom first (Kodi's GUI framebuffer, a GL texture, read in place). Its
/// damage counts as everywhere (dvvk_set_overlay_damage's rectangles are
/// top first).
/// # Safety
/// `e` from dvvk_create; `buf` NULL or valid for the call.
#[no_mangle]
pub unsafe extern "C" fn dvvk_set_overlay_ex(
    e: *mut Engine,
    buf: *const crate::overlay::Dmabuf,
    id: u64,
    flags: u32,
) -> i32 {
    if flags & !DVVK_OVERLAY_FLIP_Y != 0 {
        return DVVK_INVALID;
    }
    let flip = flags & DVVK_OVERLAY_FLIP_Y != 0;
    with_engine(e, "overlay", DVVK_INVALID, DVVK_UNSUPPORTED, |e| match e.set_shell(buf.as_ref(), id, flip) {
        Ok(()) => 0,
        Err(err) => {
            log_error("overlay", err);
            DVVK_UNSUPPORTED
        }
    })
}

/// The next dvvk_set_overlay's buffer differs from the one before it only in
/// these `count` rectangles (x, y, w, h each; count 0: the same picture).
/// Without it, a new buffer counts as changed everywhere.
/// # Safety
/// `e` from dvvk_create; `rects` holds `count` * 4 values.
#[no_mangle]
pub unsafe extern "C" fn dvvk_set_overlay_damage(e: *mut Engine, rects: *const u32, count: u32) -> i32 {
    with_engine(e, "overlay damage", DVVK_INVALID, DVVK_BACKEND, |e| {
        let Some(values) = slice(rects, count as usize * 4) else { return DVVK_INVALID };
        let r: Vec<[u32; 4]> = values.as_chunks::<4>().0.to_vec();
        e.set_shell_damage(&r);
        0
    })
}

/// 1 if a fence could not be attached as an implicit fence (an older
/// kernel): wait for each ticket before committing the output or drawing
/// into the overlay again. 0 otherwise.
/// # Safety
/// `e` from dvvk_create.
#[no_mangle]
pub unsafe extern "C" fn dvvk_implicit_failed(e: *mut Engine) -> i32 {
    // NULL or a panic: report failure, so the caller waits for each ticket.
    with_engine(e, "implicit", 1, 1, |e| e.implicit_failed as i32)
}

/// The ticket of the frame that read overlay `id`, once (0: not read).
/// # Safety
/// `e` from dvvk_create.
#[no_mangle]
pub unsafe extern "C" fn dvvk_overlay_ticket(e: *mut Engine, id: u64) -> u64 {
    with_engine(e, "overlay ticket", 0, 0, |e| e.overlay_ticket(id))
}

/// Plans and submits a frame without waiting. 0 and `*ticket`, or a dv_status.
/// The output dmabuf carries the frame's implicit write fence on return.
/// # Safety
/// `e` from dvvk_create; `frame`/metadata valid for the call; `ticket` writable.
#[no_mangle]
pub unsafe extern "C" fn dvvk_submit(e: *mut Engine, frame: *const DvvkFrame, ticket: *mut u64) -> i32 {
    if ticket.is_null() {
        return DVVK_INVALID;
    }
    *ticket = 0;
    with_engine(e, "submit", DVVK_INVALID, DVVK_BACKEND, |e| {
        let Some(f) = frame.as_ref().and_then(frame_in) else { return DVVK_INVALID };
        match e.submit(&f) {
            Ok((status, t)) => {
                *ticket = t;
                status
            }
            Err(err) => {
                log_error("submit", err);
                DVVK_BACKEND
            }
        }
    })
}

/// dvvk_set_output_mode (optional symbol): the output from the next frame.
///
/// # Safety
/// `e` must be an engine from dvvk_create (or NULL); `mode` valid.
#[no_mangle]
pub unsafe extern "C" fn dvvk_set_output_mode(e: *mut Engine, mode: *const crate::map::OutputMode) -> i32 {
    let Some(mode) = mode.as_ref() else { return DVVK_INVALID };
    with_engine(e, "set_output_mode", DVVK_INVALID, DVVK_BACKEND, |e| match e.set_output_mode(mode) {
        Ok(()) => 0,
        Err(err) => {
            log_error("set_output_mode", err);
            DVVK_UNSUPPORTED
        }
    })
}

/// dvvk_output_signal (optional symbol): the last frame's HDR static metadata.
///
/// # Safety
/// `e` must be an engine from dvvk_create (or NULL); `out` valid.
#[no_mangle]
pub unsafe extern "C" fn dvvk_output_signal(e: *mut Engine, out: *mut crate::map::HdrSignal) -> i32 {
    let Some(out) = out.as_mut() else { return DVVK_INVALID };
    with_engine(e, "output_signal", DVVK_INVALID, DVVK_BACKEND, |e| {
        *out = e.output_signal();
        0
    })
}

/// The CM4 / L2 result of the last frame planned (dvvk_plan.dm_status:
/// DVVK_CM4_STATUS_* | L2 blocks removed << 8; dv-engine-vk 0.1.0-18, an
/// optional symbol). UINT32_MAX for NULL or a panic.
/// # Safety
/// `e` from dvvk_create.
#[no_mangle]
pub unsafe extern "C" fn dvvk_dm_status(e: *mut Engine) -> u32 {
    with_engine(e, "dm status", u32::MAX, u32::MAX, |e| e.dm_status)
}

/// Never blocks: *done 1 when the frame is finished; *flags its error flags
/// (1 range, 2 overflow, 0x100 overlay colour) once done.
/// # Safety
/// `e` from dvvk_create; out pointers writable.
#[no_mangle]
pub unsafe extern "C" fn dvvk_poll(e: *mut Engine, ticket: u64, done: *mut i32, flags: *mut u32) -> i32 {
    if done.is_null() {
        return DVVK_INVALID;
    }
    with_engine(e, "poll", DVVK_INVALID, DVVK_BACKEND, |e| match e.poll(ticket) {
        Ok((d, f)) => {
            *done = d as i32;
            if !flags.is_null() {
                *flags = f;
            }
            0
        }
        Err(err) => {
            log_error("poll", err);
            DVVK_BACKEND
        }
    })
}

/// Blocks up to `timeout_ns`: 1 done, 0 timed out, < 0 failure.
/// # Safety
/// `e` from dvvk_create.
#[no_mangle]
pub unsafe extern "C" fn dvvk_wait(e: *mut Engine, ticket: u64, timeout_ns: u64) -> i32 {
    with_engine(e, "wait", DVVK_INVALID, DVVK_BACKEND, |e| match e.wait(ticket, timeout_ns) {
        Ok(d) => d as i32,
        Err(err) => {
            log_error("wait", err);
            DVVK_BACKEND
        }
    })
}

/// Counters: frames whose decode was waited for on the GPU (the surface's
/// write fence), and by vaSyncSurface.
/// # Safety
/// `e` from dvvk_create.
#[no_mangle]
pub unsafe extern "C" fn dvvk_decode_waits(e: *mut Engine, fence: *mut u64, vasync: *mut u64) {
    with_engine(e, "decode waits", (), (), |e| {
        if !fence.is_null() {
            *fence = e.decode_fence_waits;
        }
        if !vasync.is_null() {
            *vasync = e.decode_vasync_waits;
        }
    })
}

/// # Safety
/// `e` from dvvk_create; `rgba` 2160 rows of `stride` bytes.
#[no_mangle]
pub unsafe extern "C" fn dvvk_set_overlay_rgba(e: *mut Engine, rgba: *const u8, stride: usize) {
    with_engine(e, "overlay rgba", (), (), |e| {
        if stride < crate::engine::CANVAS_W as usize * 4 {
            return log_error("overlay rgba", "stride below a row");
        }
        match stride.checked_mul(crate::engine::CANVAS_H as usize).and_then(|n| slice(rgba, n)) {
            Some(bytes) => e.set_overlay_rgba(bytes, stride),
            None => log_error("overlay rgba", "NULL picture"),
        }
    })
}

/// # Safety
/// `e` from dvvk_create.
#[no_mangle]
pub unsafe extern "C" fn dvvk_reset(e: *mut Engine) {
    with_engine(e, "reset", (), (), |e| e.reset())
}

/// Retire every submitted command, including a failed export's hidden ticket.
/// 1 complete, 0 timeout, negative failure. Does not destroy or release imports.
/// # Safety
/// `e` from dvvk_create; calls on this engine externally serialized.
#[no_mangle]
pub unsafe extern "C" fn dvvk_drain(e: *mut Engine, timeout_ns: u64) -> i32 {
    with_engine(e, "drain", DVVK_INVALID, DVVK_BACKEND, |e| match e.drain(timeout_ns) {
        Ok(done) => done as i32,
        Err(err) => {
            log_error("drain", err);
            DVVK_BACKEND
        }
    })
}

/// Checked reset; 1 reset, 0 timeout, negative failure. Never heals poison.
/// # Safety
/// `e` from dvvk_create; calls on this engine externally serialized.
#[no_mangle]
pub unsafe extern "C" fn dvvk_reset_checked(e: *mut Engine, timeout_ns: u64) -> i32 {
    with_engine(e, "reset", DVVK_INVALID, DVVK_BACKEND, |e| match e.reset_checked(timeout_ns) {
        Ok(done) => done as i32,
        Err(err) => {
            log_error("reset", err);
            DVVK_BACKEND
        }
    })
}

/// # Safety
/// `e` from dvvk_create, not used afterwards.
#[no_mangle]
pub unsafe extern "C" fn dvvk_destroy(e: *mut Engine) {
    if !e.is_null() {
        // A panic while dropping leaks what is left rather than unwinding into C.
        guarded("destroy", (), || drop(Box::from_raw(e)));
    }
}
