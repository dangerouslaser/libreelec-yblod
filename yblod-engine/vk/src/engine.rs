//! The engine: a frame's plan (yblod's host code), its surfaces imported once,
//! the route's shaders and the pack into an output buffer.
//!
//! Phase 1: staged shaders 1:1 with yblod's kernels, one synchronous submit
//! per frame (the comparison harness). The asynchronous ring is phase 2.

use crate::device::{Device, Error, Result};
use crate::gpu::{self, Bind, DeviceBuffer, HostBuffer, OneShot, Pipeline, PushDescriptor};
use crate::interop::{dmabuf, va};
use crate::overlay::{self, Sources};
use crate::plan::{self, Plan, PlanIn};
use ash::vk;
use std::collections::HashMap;

pub const CANVAS_W: u32 = 3840;
pub const CANVAS_H: u32 = 2160;
const MAX_W: u32 = 4096;
const MAX_H: u32 = 4096;

pub struct FrameIn<'a> {
    pub plan: PlanIn,
    pub bl_surface: u32,
    pub el_surface: u32,
    pub metadata: &'a [u8],
    pub output: u32,
    /// The overlay comes from the engine's sources (set_subtitles /
    /// set_shell): whether there is one, and the metadata's overlay edge,
    /// are the engine's to decide.
    pub auto_overlay: bool,
    /// Explicit sync: the frame writes its output only once the release
    /// timeline reaches this point (the compositor is done with the buffer).
    pub release_wait: u64,
}

pub struct Output {
    buffer: dmabuf::ImportedBuffer,
    stride: u32,
    fd: i32,    // a dup, for the implicit fence
}

#[repr(C)]
#[derive(Clone, Copy)]
struct PackPush {
    active: [u32; 4],
    black: [u32; 4],
    placement: [u32; 4],
    w: u32,
    h: u32,
    stride_words: u32,
    packet_count: u32,
    top_left: u32,
    source_w: u32,
    source_h: u32,
    nearest: u32,
}

#[repr(C)]
#[derive(Clone, Copy)]
struct ResizePush {
    source: [u32; 2],
    dest: [u32; 2],
    top_left: u32,
}

struct FelPipelines {
    vertical_pair: Pipeline,
    luma_phase_guide: Pipeline,
    phase_vertical_uv: Pipeline,
    mmr_dual_horizontal: Pipeline,
    scale_horizontal: Pipeline,
    table_add: Pipeline,
    mmr_dual: Pipeline,            // mmr64_lut_dual (EL planes already full chroma size)
    mmr_single: [Pipeline; 3],     // mmr64_lut, mmr96, mmr (128)
    equal: [Pipeline; 3],          // luma_equal, phase, phase_guide (full-size EL)
    piecewise: [Pipeline; 3],      // 4:2:2 P010, 4:2:2 P010 order-2 chroma, 4:2:0 NV12
}

// Offsets in the tables buffer (256-aligned).
const T_MAPPING: u64 = 0;
const T_RESIDUAL: u64 = 2048;
const T_PARAMS: u64 = 14336;
const T_CHROMA_MAPPING: u64 = 15360;
const T_LUT: u64 = 19456;
const T_SINGLE: u64 = 68608;
const T_LUMA: u64 = 74752;
const T_RESHAPE: u64 = 76800;
const T_END: u64 = 81408;

// FEL intermediates, as opencl_backend.c's V, VP, BP(+1), G, ES(+1).
const F_V: usize = 0;
const F_VP: usize = 1;
const F_BP: usize = 2;
const F_G: usize = 3;
const F_ES: usize = 4;

fn bytes_of<T>(v: &[T]) -> &[u8] {
    unsafe { std::slice::from_raw_parts(v.as_ptr() as *const u8, std::mem::size_of_val(v)) }
}

/// One frame in flight: its command buffer and everything the CPU writes for
/// it, so the next frames can be prepared while it runs.
struct Ctx {
    pool: vk::CommandPool,
    cmd: vk::CommandBuffer,
    tables: HostBuffer,
    packets: HostBuffer,
    error: HostBuffer,
    gui_coeff: HostBuffer,
    gui_error: HostBuffer,
    decode: [vk::Semaphore; 3],   // the decoder's write fences (BL, EL), the shell overlay's
    done: vk::Semaphore,          // exported as the output's implicit fence
    ticket: u64,                  // the timeline value its submit signals; 0 = never used
}

pub const RING: usize = 4;

pub struct Engine {
    pub d: Device,
    ring: Vec<Ctx>,
    next: usize,
    timeline: vk::Semaphore,
    release: Option<vk::Semaphore>,   // the compositor's release timeline (explicit sync)
    ticket: u64,
    vasync: bool,
    pub decode_fence_waits: u64,
    pub decode_vasync_waits: u64,
    va: va::VADisplay,
    push: PushDescriptor,
    sampler: vk::Sampler,
    single: Pipeline,
    fel: FelPipelines,
    fel_buffers: [DeviceBuffer; 5],
    pack: Vec<Pipeline>,      // [(source * 2 + overlay) * 3 + PACK]
    fel_chroma: Pipeline,
    staged: bool,
    overlay: HostBuffer,
    gui_coeff: HostBuffer,
    gui_error: HostBuffer,
    gui_colours: DeviceBuffer,
    gui_tiles: DeviceBuffer,
    gui_keys: DeviceBuffer,
    keys_valid: bool,
    overlay_prepare: [Pipeline; 2],   // from the test RGBA buffer, from the sources
    linear: vk::Sampler,
    pub sources: Sources,
    sources_used: bool,       // the overlay comes from `sources`, not set_overlay_rgba
    prev_overlay: bool,
    // The prepared overlay is current for this picture and these colour coefficients.
    overlay_dirty: bool,
    overlay_coeff: [f32; 32],
    resize_prepare: Pipeline,
    planes: [DeviceBuffer; 3],
    ymap: DeviceBuffer,
    tables: HostBuffer,
    packets: HostBuffer,
    error: HostBuffer,
    surfaces: HashMap<u32, va::SurfaceImport>,
    outputs: Vec<Option<Output>>,
    shot: OneShot,
    resize_key: Option<[u32; 5]>,
    plan: Box<Plan>,
    pub last_error_flags: u32,
    last_plan_ms: f64,
    overlay_error_flag: u32,
    overlay_prepared_by: Option<usize>,
    pub implicit_failed: bool,
    trace: Option<(u32, u32, u32, [u32; 2], u32, u32, u32, u32)>,
    // DVVK_PROFILE=1: GPU timestamps around the reconstruction and the pack,
    // and the CPU planning time, averaged and printed every 48 frames.
    profile: Option<vk::QueryPool>,
    profile_sum: [f64; 3],
    profile_n: u32,
}

impl Engine {
    pub fn new(drm_fd: i32, va_display: va::VADisplay) -> Result<Self> {
        if !plan::layout_matches() {
            return Err(Error::Unsupported("plan.h and plan.rs disagree".into()));
        }
        let d = Device::new(drm_fd)?;
        let storage = vk::DescriptorType::STORAGE_BUFFER;
        let sampled = vk::DescriptorType::COMBINED_IMAGE_SAMPLER;
        // source_tunnel.cl has no FP_CONTRACT pragma, so OpenCL's default (ON)
        // applies and IGC fuses the resize lerps: fused (1) matches it byte for
        // byte; DVVK_RESIZE_FMA=0 is the uncontracted variant, for comparison.
        let fma = std::env::var("DVVK_RESIZE_FMA").ok().and_then(|v| v.parse().ok()).unwrap_or(1u32);
        let single = Pipeline::new(&d, "single_polynomial", &[sampled, sampled, storage, storage, storage, storage, storage], 12, &[])?;
        let blend_fma = std::env::var("DVVK_BLEND_FMA").ok().and_then(|v| v.parse().ok()).unwrap_or(1u32);
        let mut pack_bindings = vec![storage; 9];
        pack_bindings.extend([sampled, sampled, sampled, storage, storage, storage]);
        let pack_push = std::mem::size_of::<PackPush>() as u32;
        let mut pack = Vec::new();
        for source in 0..3u32 {
            for overlay in 0..2u32 {
                for kind in 0..3u32 {
                    pack.push(Pipeline::new(&d, "pack", &pack_bindings, pack_push,
                        &[(0, kind), (1, fma), (2, overlay), (3, blend_fma), (4, source)])?);
                }
            }
        }
        let fel_chroma = Pipeline::new(&d, "fel_chroma",
            &[sampled, sampled, sampled, storage, storage, storage, storage, storage, storage, storage, storage], 32, &[])?;
        let staged = std::env::var("DVVK_STAGED").map(|v| v == "1").unwrap_or(false);
        let fel = FelPipelines {
            vertical_pair: Pipeline::new(&d, "fel_vertical_pair", &[sampled, storage, storage], 20, &[])?,
            luma_phase_guide: Pipeline::new(&d, "fel_luma_phase_guide", &[sampled, sampled, storage, storage, storage, storage, storage, storage, storage], 20, &[])?,
            phase_vertical_uv: Pipeline::new(&d, "fel_phase_vertical_uv", &[sampled, storage, storage, storage], 20, &[])?,
            mmr_dual_horizontal: Pipeline::new(&d, "fel_mmr_dual_horizontal", &[storage; 12], 16, &[])?,
            scale_horizontal: Pipeline::new(&d, "fel_scale_horizontal", &[storage; 3], 16, &[])?,
            table_add: Pipeline::new(&d, "table_add", &[storage; 6], 12, &[])?,
            mmr_dual: Pipeline::new(&d, "fel_mmr_dual_horizontal", &[storage; 12], 16, &[(0, 0)])?,
            mmr_single: [
                Pipeline::new(&d, "fel_mmr_single", &[storage; 8], 12, &[(0, 0)])?,
                Pipeline::new(&d, "fel_mmr_single", &[storage; 8], 12, &[(0, 1)])?,
                Pipeline::new(&d, "fel_mmr_single", &[storage; 8], 12, &[(0, 2)])?,
            ],
            equal: [
                Pipeline::new(&d, "fel_equal", &[sampled, sampled, storage, storage, storage, storage, storage, storage], 20, &[(0, 0)])?,
                Pipeline::new(&d, "fel_equal", &[sampled, sampled, storage, storage, storage, storage, storage, storage], 20, &[(0, 1)])?,
                Pipeline::new(&d, "fel_equal", &[sampled, sampled, storage, storage, storage, storage, storage, storage], 20, &[(0, 2)])?,
            ],
            piecewise: [
                Pipeline::new(&d, "piecewise", &[sampled, sampled, storage, storage, storage, storage, storage, storage], 32, &[(0, 1), (1, 10), (2, 0), (3, 1)])?,
                Pipeline::new(&d, "piecewise", &[sampled, sampled, storage, storage, storage, storage, storage, storage], 32, &[(0, 1), (1, 10), (2, 1), (3, 1)])?,
                Pipeline::new(&d, "piecewise", &[sampled, sampled, storage, storage, storage, storage, storage, storage], 32, &[(0, 0), (1, 8), (2, 0), (3, 1)])?,
            ],
        };
        let quarter = (MAX_W / 2 * MAX_H / 2 * 2) as u64;
        let fel_buffers = [
            DeviceBuffer::new(&d, (MAX_W / 2 * MAX_H * 2) as u64)?,
            DeviceBuffer::new(&d, quarter / 2)?,
            DeviceBuffer::new(&d, 2 * quarter)?,
            DeviceBuffer::new(&d, quarter)?,
            DeviceBuffer::new(&d, 2 * quarter)?,
        ];
        let overlay = HostBuffer::new(&d, (CANVAS_W * CANVAS_H * 4) as u64, vk::BufferUsageFlags::STORAGE_BUFFER)?;
        let gui_coeff = HostBuffer::new(&d, 128, vk::BufferUsageFlags::STORAGE_BUFFER)?;
        let gui_error = HostBuffer::new(&d, 16, vk::BufferUsageFlags::STORAGE_BUFFER)?;
        let gui_colours = DeviceBuffer::new(&d, (CANVAS_W * CANVAS_H * 16) as u64)?;
        let gui_tiles = DeviceBuffer::new(&d, (CANVAS_W.div_ceil(16) * CANVAS_H.div_ceil(16) * 4) as u64)?;
        let prepare_bindings = [storage, storage, storage, storage, sampled, storage, storage, storage, storage, storage];
        let overlay_prepare = [
            Pipeline::new(&d, "overlay_prepare", &prepare_bindings, 36, &[(0, 0)])?,
            Pipeline::new(&d, "overlay_prepare", &prepare_bindings, 36, &[(0, 1)])?,
        ];
        let gui_keys = DeviceBuffer::new(&d, (CANVAS_W * CANVAS_H * 4) as u64)?;
        let linear = {
            let info = vk::SamplerCreateInfo::default()
                .mag_filter(vk::Filter::LINEAR)
                .min_filter(vk::Filter::LINEAR)
                .address_mode_u(vk::SamplerAddressMode::CLAMP_TO_EDGE)
                .address_mode_v(vk::SamplerAddressMode::CLAMP_TO_EDGE);
            unsafe { d.device.create_sampler(&info, None) }?
        };
        let sources = Sources::new(&d)?;
        let resize_prepare = Pipeline::new(&d, "resize_prepare", &[storage], std::mem::size_of::<ResizePush>() as u32, &[])?;
        let luma_bytes = (MAX_W * MAX_H * 2) as u64;
        let planes = [
            DeviceBuffer::new(&d, luma_bytes)?,
            DeviceBuffer::new(&d, luma_bytes / 2)?,
            DeviceBuffer::new(&d, luma_bytes / 2)?,
        ];
        let ymap = DeviceBuffer::new(&d, 2 * 4096 * 16)?;
        let tables = HostBuffer::new(&d, T_END.next_multiple_of(4096), vk::BufferUsageFlags::STORAGE_BUFFER)?;
        let packets = HostBuffer::new(&d, 640, vk::BufferUsageFlags::STORAGE_BUFFER)?;
        let error = HostBuffer::new(&d, 16, vk::BufferUsageFlags::STORAGE_BUFFER)?;
        let sampler = gpu::nearest_sampler(&d)?;
        let push = PushDescriptor::new(&d);
        let shot = OneShot::new(&d)?;
        let mut ring = Vec::new();
        for _ in 0..RING {
            let pool = unsafe {
                d.device.create_command_pool(
                    &vk::CommandPoolCreateInfo::default()
                        .queue_family_index(d.queue_family)
                        .flags(vk::CommandPoolCreateFlags::RESET_COMMAND_BUFFER),
                    None,
                )
            }?;
            let cmd = unsafe {
                d.device.allocate_command_buffers(&vk::CommandBufferAllocateInfo::default().command_pool(pool).command_buffer_count(1))
            }?[0];
            let sem = |d: &Device| -> Result<vk::Semaphore> { crate::interop::sync::exportable_semaphore(d) };
            ring.push(Ctx {
                pool,
                cmd,
                tables: HostBuffer::new(&d, T_END.next_multiple_of(4096), vk::BufferUsageFlags::STORAGE_BUFFER)?,
                packets: HostBuffer::new(&d, 640, vk::BufferUsageFlags::STORAGE_BUFFER)?,
                error: HostBuffer::new(&d, 16, vk::BufferUsageFlags::STORAGE_BUFFER)?,
                gui_coeff: HostBuffer::new(&d, 128, vk::BufferUsageFlags::STORAGE_BUFFER)?,
                gui_error: HostBuffer::new(&d, 16, vk::BufferUsageFlags::STORAGE_BUFFER)?,
                decode: [sem(&d)?, sem(&d)?, sem(&d)?],
                done: sem(&d)?,
                ticket: 0,
            });
        }
        let mut type_info = vk::SemaphoreTypeCreateInfo::default().semaphore_type(vk::SemaphoreType::TIMELINE).initial_value(0);
        let mut export = vk::ExportSemaphoreCreateInfo::default().handle_types(vk::ExternalSemaphoreHandleTypeFlags::OPAQUE_FD);
        let timeline = unsafe {
            d.device.create_semaphore(&vk::SemaphoreCreateInfo::default().push_next(&mut type_info).push_next(&mut export), None)
        }?;
        let vasync = std::env::var("DVVK_VASYNC").map(|v| v == "1").unwrap_or(false);
        Ok(Engine {
            ring,
            next: 0,
            timeline,
            release: None,
            ticket: 0,
            vasync,
            decode_fence_waits: 0,
            decode_vasync_waits: 0,
            push,
            sampler,
            single,
            fel,
            fel_buffers,
            pack,
            fel_chroma,
            staged,
            overlay,
            gui_coeff,
            gui_error,
            gui_colours,
            gui_tiles,
            gui_keys,
            keys_valid: false,
            overlay_prepare,
            linear,
            sources,
            sources_used: false,
            prev_overlay: false,
            overlay_dirty: true,
            overlay_coeff: [0.0; 32],
            resize_prepare,
            planes,
            ymap,
            tables,
            packets,
            error,
            surfaces: HashMap::new(),
            outputs: Vec::new(),
            shot,
            resize_key: None,
            plan: Plan::boxed(),
            last_error_flags: 0,
            last_plan_ms: 0.0,
            overlay_error_flag: 0,
            overlay_prepared_by: None,
            implicit_failed: false,
            trace: None,
            profile: None,
            profile_sum: [0.0; 3],
            profile_n: 0,
            va: va_display,
            d,
        })
    }

    /// A linear XRGB8888 3840x2160 dmabuf as output `slot`.
    pub fn set_output(&mut self, slot: u32, fd: i32, stride: u32) -> Result<()> {
        if stride < CANVAS_W * 4 || stride % 16 != 0 {
            return Err(Error::Unsupported("output stride".into()));
        }
        let buffer = dmabuf::import_buffer(&self.d, fd, stride as u64 * CANVAS_H as u64)?;
        let slot = slot as usize;
        if self.outputs.len() <= slot {
            self.outputs.resize_with(slot + 1, || None);
        }
        self.idle();
        if let Some(old) = self.outputs[slot].take() {
            old.buffer.destroy(&self.d);
            unsafe { libc::close(old.fd) };
        }
        let fd = unsafe { libc::fcntl(fd, libc::F_DUPFD_CLOEXEC, 0) };
        self.outputs[slot] = Some(Output { buffer, stride, fd });
        Ok(())
    }

    /// The overlay picture (RGBA8 premultiplied sRGB, 3840x2160, rows top
    /// first) used by frames with `overlay` set. Phase 1: copied in.
    pub fn set_overlay_rgba(&mut self, rgba: &[u8], stride: usize) {
        let dst = self.overlay.bytes_mut();
        let row = (CANVAS_W * 4) as usize;
        for y in 0..CANVAS_H as usize {
            dst[y * row..(y + 1) * row].copy_from_slice(&rgba[y * stride..y * stride + row]);
        }
        self.overlay_dirty = true;
    }

    /// mpv's subtitles / OSD bitmaps for the following frames (none: empty).
    pub fn set_subtitles(&mut self, parts: &[overlay::SubPart]) -> Result<()> {
        self.sources_used = true;
        let timeline = self.timeline;
        let d = &self.d;
        let wait = |t: u64| {
            if t > 0 {
                let sems = [timeline];
                let values = [t];
                let _ = unsafe { d.device.wait_semaphores(&vk::SemaphoreWaitInfo::default().semaphores(&sems).values(&values), u64::MAX) };
            }
        };
        self.sources.set_subtitles(parts, (CANVAS_W, CANVAS_H), wait)
    }

    /// The shell's OSD buffer (KWin's forwarded dmabuf) for the following
    /// frames, or none. `id` names it for overlay_ticket.
    pub fn set_shell(&mut self, buf: Option<&overlay::Dmabuf>, id: u64) -> Result<()> {
        self.sources_used = true;
        let ticket = self.ticket;
        let timeline = self.timeline;
        let d = &self.d;
        let idle = || {
            if ticket > 0 {
                let sems = [timeline];
                let values = [ticket];
                let _ = unsafe { d.device.wait_semaphores(&vk::SemaphoreWaitInfo::default().semaphores(&sems).values(&values), u64::MAX) };
            }
        };
        self.sources.set_shell(d, buf, id, idle)
    }

    /// The ticket of the frame that read overlay `id` (0: not read yet; the
    /// caller may give the buffer back once that ticket is done).
    pub fn overlay_ticket(&mut self, id: u64) -> u64 {
        self.sources.consumed.remove(&id).unwrap_or(0)
    }

    /// Forget imported surfaces (new decoder pool: seek, new file).
    pub fn reset(&mut self) {
        self.idle();
        for (_, s) in self.surfaces.drain() {
            s.destroy(&self.d);
        }
        self.resize_key = None;
    }

    /// The surface's planes, imported once. A surface id can come back for a
    /// different allocation (a new decoder pool after a seek or a new file):
    /// the cached import stands only while its dmabuf is the same one.
    fn surface(&mut self, id: u32, w: u32, h: u32) -> Result<()> {
        if let Some(s) = self.surfaces.get(&id) {
            if s.luma.width == w && s.luma.height == h && va::surface_inode(self.va, id) == Some(s.inode) {
                return Ok(());
            }
            self.idle();
            let s = self.surfaces.remove(&id).unwrap();
            s.destroy(&self.d);
        }
        let s = va::import_surface(&self.d, self.va, id, w, h)?;
        self.surfaces.insert(id, s);
        Ok(())
    }

    /// linux-drm-syncobj-v1: the frames' timeline (acquire points: the
    /// tickets) and a new release timeline the compositor signals, both as
    /// DRM syncobj fds for wp_linux_drm_syncobj_manager_v1.import_timeline.
    pub fn timelines(&mut self) -> Result<(i32, i32)> {
        let get = |s: vk::Semaphore| -> Result<i32> {
            let info = vk::SemaphoreGetFdInfoKHR::default()
                .semaphore(s)
                .handle_type(vk::ExternalSemaphoreHandleTypeFlags::OPAQUE_FD);
            Ok(unsafe { self.d.semaphore_fd.get_semaphore_fd(&info) }?)
        };
        if self.release.is_none() {
            let mut type_info = vk::SemaphoreTypeCreateInfo::default().semaphore_type(vk::SemaphoreType::TIMELINE).initial_value(0);
            let mut export = vk::ExportSemaphoreCreateInfo::default().handle_types(vk::ExternalSemaphoreHandleTypeFlags::OPAQUE_FD);
            let sem = unsafe {
                self.d.device.create_semaphore(&vk::SemaphoreCreateInfo::default().push_next(&mut type_info).push_next(&mut export), None)
            }?;
            self.release = Some(sem);
        }
        let acquire = get(self.timeline)?;
        let release = match get(self.release.unwrap()) {
            Ok(fd) => fd,
            Err(e) => {
                unsafe { libc::close(acquire) };
                return Err(e);
            }
        };
        Ok((acquire, release))
    }

    /// Wait until the GPU has finished everything submitted.
    pub fn idle(&self) {
        if self.ticket > 0 {
            let _ = self.wait(self.ticket, u64::MAX);
        }
    }

    /// Blocks until frame `ticket` is done (or `timeout_ns`). Ok(true) if done.
    pub fn wait(&self, ticket: u64, timeout_ns: u64) -> Result<bool> {
        let sems = [self.timeline];
        let values = [ticket];
        match unsafe {
            self.d.device.wait_semaphores(&vk::SemaphoreWaitInfo::default().semaphores(&sems).values(&values), timeout_ns)
        } {
            Ok(()) => Ok(true),
            Err(vk::Result::TIMEOUT) => Ok(false),
            Err(e) => Err(e.into()),
        }
    }

    /// Whether frame `ticket` is done, and its error flags (range 1, overflow
    /// 2, overlay colour << 8) if its context hasn't been reused yet. Never blocks.
    pub fn poll(&self, ticket: u64) -> Result<(bool, u32)> {
        let done = unsafe { self.d.device.get_semaphore_counter_value(self.timeline) }? >= ticket;
        let ctx = &self.ring[((ticket.max(1) - 1) % RING as u64) as usize];
        let flags = if done && ctx.ticket == ticket {
            u32::from_le_bytes(ctx.error.bytes()[..4].try_into().unwrap())
                | (u32::from_le_bytes(ctx.gui_error.bytes()[..4].try_into().unwrap()) << 8)
        } else {
            0
        };
        Ok((done, flags))
    }

    /// The decoder's write fence on a surface, as a semaphore the frame waits
    /// for (no CPU wait); vaSyncSurface if the kernel can't export it.
    fn decode_wait(&mut self, ctx: usize, k: usize, id: u32) -> Result<Option<vk::Semaphore>> {
        let fd = self.surfaces[&id].fd;
        if !self.vasync {
            if let Ok(sync_file) = crate::interop::sync::export_sync_file(fd, crate::interop::sync::DMA_BUF_SYNC_READ) {
                if crate::interop::sync::signalled(sync_file) {
                    unsafe { libc::close(sync_file) };
                    return Ok(None);
                }
                let sem = self.ring[ctx].decode[k];
                match crate::interop::sync::semaphore_from_sync_file(&self.d, sem, sync_file) {
                    Ok(()) => {
                        self.decode_fence_waits += 1;
                        return Ok(Some(sem));
                    }
                    Err(_) => unsafe {
                        libc::close(sync_file);
                    },
                }
            }
        }
        self.decode_vasync_waits += 1;
        unsafe { va::vaSyncSurface(self.va, id) };
        Ok(None)
    }

    /// Plans, records and runs one frame synchronously (the comparison
    /// harness). Ok(0) or Ok(dv_status != 0: not this engine's frame).
    pub fn render(&mut self, f: &FrameIn) -> Result<i32> {
        let (status, ticket) = self.submit(f)?;
        if status != 0 {
            return Ok(status);
        }
        self.wait(ticket, u64::MAX)?;
        self.last_error_flags = self.poll(ticket)?.1;
        if let Some(q) = self.profile {
            let mut ts = [0u64; 3];
            unsafe {
                self.d.device.get_query_pool_results(q, 0, &mut ts, vk::QueryResultFlags::TYPE_64 | vk::QueryResultFlags::WAIT)?;
            }
            let period = self.d.timestamp_period as f64 / 1e6;
            self.profile_sum[0] += (ts[1].wrapping_sub(ts[0])) as f64 * period;
            self.profile_sum[1] += (ts[2].wrapping_sub(ts[1])) as f64 * period;
            self.profile_sum[2] += self.last_plan_ms;
            self.profile_n += 1;
            if self.profile_n == 48 {
                let n = self.profile_n as f64;
                eprintln!("dvvk profile: reconstruction {:.2} ms, pack {:.2} ms (GPU), plan {:.2} ms (CPU), mean of 48",
                    self.profile_sum[0] / n, self.profile_sum[1] / n, self.profile_sum[2] / n);
                self.profile_sum = [0.0; 3];
                self.profile_n = 0;
            }
        }
        Ok(0)
    }

    /// Plans and submits one frame into output `f.output`; returns at once.
    /// (status, ticket): status 0 and the ticket `poll`/`wait` take, or a
    /// dv_status (not this engine's frame: show an ordinary picture). The
    /// output dmabuf carries the frame's fence as an implicit write fence, so
    /// it can be committed to the compositor right away.
    pub fn submit(&mut self, f: &FrameIn) -> Result<(i32, u64)> {
        let ci = self.next;
        if self.ring[ci].ticket > 0 {
            self.wait(self.ring[ci].ticket, u64::MAX)?;   // back-pressure: RING frames in flight
        }
        if self.profile.is_none() && std::env::var("DVVK_PROFILE").map(|v| v == "1").unwrap_or(false) {
            let info = vk::QueryPoolCreateInfo::default().query_type(vk::QueryType::TIMESTAMP).query_count(3);
            self.profile = Some(unsafe { self.d.device.create_query_pool(&info, None) }?);
        }
        let mut plan_in = f.plan;
        if f.auto_overlay {
            plan_in.overlay = self.sources.has_content() as u32;
            plan_in.overlay_visible_before = self.prev_overlay as u32;
        }
        let plan_start = std::time::Instant::now();
        let status = self.plan.fill(&plan_in, f.metadata);
        self.last_plan_ms = plan_start.elapsed().as_secs_f64() * 1e3;
        if status != 0 {
            return Ok((status, 0));
        }
        let p = &*self.plan;
        if std::env::var_os("DVVK_TRACE").is_some() {
            let key = (p.route, p.equal, p.dual, p.chroma_kind, p.layout, p.order2, p.depth, p.pack);
            if self.trace != Some(key) {
                eprintln!("dvvk: route {} equal {} dual {} chroma {:?} layout {} order2 {} depth {} pack {}",
                          key.0, key.1, key.2, key.3, key.4, key.5, key.6, key.7);
                self.trace = Some(key);
            }
        }
        let p = &*self.plan;
        if self.outputs.get(f.output as usize).and_then(|o| o.as_ref()).is_none() {
            return Err(Error::Missing("output"));
        }
        let route = p.route;
        let (w, h) = (p.width, p.height);
        let el_w = if p.el_scale == 2 { w / 2 } else { w };
        let el_h = if p.el_scale == 2 { h / 2 } else { h };
        let needs_el = route == plan::ROUTE_DUAL;
        if route == plan::ROUTE_PIECEWISE && (p.layout == 0) != (p.depth == 8) {
            return Ok((-2, 0)); // the 4:2:0 P010 kernel isn't built with the production settings either
        }
        self.surface(f.bl_surface, w, h)?;
        if needs_el {
            self.surface(f.el_surface, el_w, el_h)?;
        }
        let mut waits = Vec::new();
        if let Some(s) = self.decode_wait(ci, 0, f.bl_surface)? {
            waits.push(s);
        }
        if needs_el {
            if let Some(s) = self.decode_wait(ci, 1, f.el_surface)? {
                waits.push(s);
            }
        }
        // The shell's OSD buffer: Qt's rendering into it may still be running.
        let compose = self.sources_used && self.sources.dirty && self.plan.overlay_visible != 0;
        if compose {
            if let Some(sh) = self.sources.shell() {
                if let Ok(sync_file) = crate::interop::sync::export_sync_file(sh.fd, crate::interop::sync::DMA_BUF_SYNC_READ) {
                    if crate::interop::sync::signalled(sync_file) {
                        unsafe { libc::close(sync_file) };
                    } else {
                        let sem = self.ring[ci].decode[2];
                        if crate::interop::sync::semaphore_from_sync_file(&self.d, sem, sync_file).is_ok() {
                            waits.push(sem);
                        } else {
                            unsafe { libc::close(sync_file) };
                        }
                    }
                }
            }
        }
        // This frame's context buffers stand in for the engine's while it is
        // recorded (the record functions read self.tables, self.error, ...).
        {
            let c = &mut self.ring[ci];
            std::mem::swap(&mut self.tables, &mut c.tables);
            std::mem::swap(&mut self.packets, &mut c.packets);
            std::mem::swap(&mut self.error, &mut c.error);
            std::mem::swap(&mut self.gui_coeff, &mut c.gui_coeff);
            std::mem::swap(&mut self.gui_error, &mut c.gui_error);
        }
        let result = self.record_submit(f, ci, &waits);
        {
            let c = &mut self.ring[ci];
            std::mem::swap(&mut self.tables, &mut c.tables);
            std::mem::swap(&mut self.packets, &mut c.packets);
            std::mem::swap(&mut self.error, &mut c.error);
            std::mem::swap(&mut self.gui_coeff, &mut c.gui_coeff);
            std::mem::swap(&mut self.gui_error, &mut c.gui_error);
        }
        let ticket = result?;
        self.ring[ci].ticket = ticket;
        self.next = (ci + 1) % RING;
        if compose {
            self.sources.used(ticket);
            self.sources.dirty = false;
            self.sources.dirty_rect = Some([0, 0, 0, 0]);
        }
        self.prev_overlay = self.plan.overlay_visible != 0;
        Ok((0, ticket))
    }

    fn record_submit(&mut self, f: &FrameIn, ci: usize, waits: &[vk::Semaphore]) -> Result<u64> {
        let p = &*self.plan;
        let out = self.outputs.get(f.output as usize).and_then(|o| o.as_ref()).ok_or(Error::Missing("output"))?;
        let (out_buffer, out_stride, out_fd) = (out.buffer.buffer, out.stride, out.fd);
        let route = p.route;
        let (w, h) = (p.width, p.height);
        let tables = self.tables.bytes_mut();
        let mut put = |offset: u64, src: &[u8]| tables[offset as usize..offset as usize + src.len()].copy_from_slice(src);
        put(T_SINGLE, bytes_of(&p.single_table));
        put(T_MAPPING, bytes_of(&p.mapping));
        put(T_RESIDUAL, bytes_of(&p.residual));
        put(T_PARAMS, bytes_of(&p.mmr_params));
        put(T_CHROMA_MAPPING, bytes_of(&p.chroma_mapping));
        put(T_LUT, bytes_of(&p.mmr_lut));
        put(T_LUMA, bytes_of(&p.luma_table));
        put(T_RESHAPE, &p.reshape);
        self.packets.bytes_mut().copy_from_slice(&p.packets);
        self.error.bytes_mut()[..4].copy_from_slice(&0u32.to_le_bytes());
        // The overlay's colour error belongs to the prepared overlay: every
        // frame that uses it reports it.
        self.gui_error.bytes_mut()[..4].copy_from_slice(&self.overlay_error_flag.to_le_bytes());
        let compose = self.sources_used && self.sources.dirty && p.overlay_visible != 0;
        let coeff_changed = self.overlay_coeff != p.gui_coeff;
        let prepare_overlay = p.overlay_visible != 0 && (compose || self.overlay_dirty || coeff_changed);
        // The area to prepare again: only the subtitles' old and new area when
        // nothing else changed; the whole canvas otherwise.
        let full = [0u32, 0, CANVAS_W, CANVAS_H];
        let rect = if compose && !self.overlay_dirty && !coeff_changed && self.keys_valid
            && std::env::var_os("DVVK_FULL_PREPARE").is_none()
        {
            match self.sources.dirty_rect {
                Some(r) if r[2] > r[0] && r[3] > r[1] => [
                    r[0] & !15,
                    r[1] & !15,
                    ((r[2] + 15) & !15).min(CANVAS_W),
                    ((r[3] + 15) & !15).min(CANVAS_H),
                ],
                Some(_) => [0, 0, 0, 0],
                None => full,
            }
        } else {
            full
        };
        let invalidate = coeff_changed || !self.keys_valid;
        if prepare_overlay {
            self.keys_valid = true;
        }
        if prepare_overlay {
            self.gui_error.bytes_mut()[..4].copy_from_slice(&0u32.to_le_bytes());
            self.overlay_prepared_by = Some(ci);
            let coeff = bytes_of(&p.gui_coeff);
            self.gui_coeff.bytes_mut()[..coeff.len()].copy_from_slice(coeff);
            self.overlay_coeff = p.gui_coeff;
            self.overlay_dirty = false;
        }

        let d = &self.d;
        let cmd = self.ring[ci].cmd;
        unsafe {
            d.device.reset_command_buffer(cmd, vk::CommandBufferResetFlags::empty())?;
            d.device.begin_command_buffer(cmd, &vk::CommandBufferBeginInfo::default().flags(vk::CommandBufferUsageFlags::ONE_TIME_SUBMIT))?;
        }
        // After everything submitted before (shared intermediates, caches).
        gpu::compute_barrier(d, cmd);
        if let Some(q) = self.profile {
            unsafe {
                d.device.cmd_reset_query_pool(cmd, q, 0, 3);
                d.device.cmd_write_timestamp2(cmd, vk::PipelineStageFlags2::TOP_OF_PIPE, q, 0);
            }
        }
        let bl = &self.surfaces[&f.bl_surface];
        gpu::acquire_foreign_images(d, cmd, &[bl.luma.image, bl.chroma.image]);
        gpu::foreign_buffer(d, cmd, out_buffer, true);

        let (first, last) = if p.row_last != 0 { (p.row_first, p.row_last) } else { (0, h) };
        // (the BL's surfaces were looked up before the uploads)
        // Fused: single layer in the pack itself; half-size-EL FEL as pass A
        // (chroma) + the pack (luma). Everything else staged.
        let source = if self.staged {
            0
        } else if route == plan::ROUTE_SINGLE && p.pack != plan::PACK_RESIZED {
            // Resized frames read 4 taps per sample: cheaper from the planes.
            1
        } else if route == plan::ROUTE_DUAL && p.equal == 0 && p.nearest != 0 {
            // Annex B stays staged until its taps are shared through a tile
            // (on the fly it recomputes each vertical tap up to 8 times).
            2
        } else {
            0
        };
        let el_view = if route == plan::ROUTE_DUAL { self.surfaces[&f.el_surface].luma.view } else { bl.luma.view };
        if source == 1 {
            // nothing before the pack
        } else if source == 2 {
            let el = &self.surfaces[&f.el_surface];
            gpu::acquire_foreign_images(d, cmd, &[el.luma.image, el.chroma.image]);
            let t = self.tables.buffer;
            let s = self.sampler;
            let (cw, ch) = (w / 2, h / 2);
            let push = [w, h, p.chroma_phase, p.nearest, p.dual, p.chroma_kind[0], p.chroma_kind[1], first / 2];
            self.dispatch(cmd, &self.fel_chroma,
                &[Bind::Sampled(bl.luma.view, s), Bind::Sampled(bl.chroma.view, s), Bind::Sampled(el.chroma.view, s),
                  Bind::Range(t, T_PARAMS, 768), Bind::Range(t, T_RESIDUAL, 12288), Bind::Range(t, T_LUT, 49152),
                  Bind::Range(t, T_CHROMA_MAPPING, 4096), Bind::Buffer(self.planes[1].buffer),
                  Bind::Buffer(self.planes[2].buffer), Bind::Buffer(self.error.buffer), Bind::Buffer(self.error.buffer)],
                &push, (cw.div_ceil(64), (last - first) / 2));
            let _ = ch;
        } else if route == plan::ROUTE_SINGLE {
            // single_polynomial_p010, letterbox window as a row offset.
            unsafe { d.device.cmd_bind_pipeline(cmd, vk::PipelineBindPoint::COMPUTE, self.single.pipeline) };
            self.push.bind(
                cmd,
                &self.single,
                &[
                    Bind::Sampled(bl.luma.view, self.sampler),
                    Bind::Sampled(bl.chroma.view, self.sampler),
                    Bind::Range(self.tables.buffer, T_SINGLE, 6144),
                    Bind::Buffer(self.planes[0].buffer),
                    Bind::Buffer(self.planes[1].buffer),
                    Bind::Buffer(self.planes[2].buffer),
                    Bind::Buffer(self.error.buffer),
                ],
            );
            gpu::push_constants(d, cmd, &self.single, &[w, h, first / 2]);
            unsafe { d.device.cmd_dispatch(cmd, (w / 2).div_ceil(16), ((last - first) / 2).div_ceil(8), 1) };
        } else if route == plan::ROUTE_PIECEWISE {
            let k = if p.depth == 8 { 2 } else if p.order2 != 0 { 1 } else { 0 };
            let pipe = &self.fel.piecewise[k];
            let rows_per = if p.layout == 1 { 1 } else { 2 };
            #[repr(C)]
            #[derive(Clone, Copy)]
            struct PiecewisePush { mask: [u32; 4], w: u32, h: u32, policy: u32, row_offset: u32 }
            let push = PiecewisePush { mask: p.narrow_mask, w, h, policy: p.sampling, row_offset: first / rows_per };
            self.dispatch(cmd, pipe,
                &[Bind::Sampled(bl.luma.view, self.sampler), Bind::Sampled(bl.chroma.view, self.sampler),
                  Bind::Range(self.tables.buffer, T_RESHAPE, 4544), Bind::Buffer(self.planes[0].buffer),
                  Bind::Buffer(self.planes[1].buffer), Bind::Buffer(self.planes[2].buffer),
                  Bind::Range(self.tables.buffer, T_LUMA, 2048), Bind::Buffer(self.error.buffer)],
                &push, ((w / 2).div_ceil(16), ((last - first) / rows_per).div_ceil(8)));
        } else {
            let el = &self.surfaces[&f.el_surface];
            gpu::acquire_foreign_images(d, cmd, &[el.luma.image, el.chroma.image]);
            if p.equal != 0 {
                self.record_fel_equal(cmd, p, bl, el, first, last);
            } else {
                self.record_fel(cmd, p, bl, el, first, last);
            }
        }
        gpu::compute_barrier(d, cmd);

        if let Some(q) = self.profile {
            unsafe { d.device.cmd_write_timestamp2(cmd, vk::PipelineStageFlags2::COMPUTE_SHADER, q, 1) };
        }
        // The overlay's tile map and colour cache, when the overlay or the
        // movie's colour metadata changed.
        if prepare_overlay && rect[2] > rect[0] && rect[3] > rect[1] {
            let s = &self.sources;
            let r = Sources::ranges();
            let from_sources = self.sources_used;
            let atlas = s.atlas[s.subs_slot].buffer;
            let shell_view = match s.shell() {
                Some(sh) if from_sources => {
                    gpu::acquire_foreign_images(d, cmd, &[sh.image.image]);
                    sh.image.view
                }
                _ => self.surfaces[&f.bl_surface].luma.view,   // unused: a valid view to bind
            };
            let (ew, eh) = (rect[2] - rect[0], rect[3] - rect[1]);
            #[repr(C)]
            #[derive(Clone, Copy)]
            struct PreparePush { w: u32, h: u32, has_shell: u32, has_subs: u32, tiles_x: u32, tile: u32, origin: [u32; 2], invalidate: u32 }
            let push = PreparePush {
                w: CANVAS_W,
                h: CANVAS_H,
                has_shell: (from_sources && s.shell.is_some()) as u32,
                has_subs: (from_sources && s.subs_parts > 0) as u32,
                tiles_x: s.tiles_x.max(1),
                tile: overlay::TILE,
                origin: [rect[0], rect[1]],
                invalidate: invalidate as u32,
            };
            self.dispatch(cmd, &self.overlay_prepare[from_sources as usize],
                &[Bind::Buffer(self.overlay.buffer), Bind::Range(atlas, r[0].0, r[0].1), Bind::Range(atlas, r[1].0, r[1].1),
                  Bind::Range(atlas, r[2].0, r[2].1), Bind::Sampled(shell_view, self.linear), Bind::Buffer(self.gui_keys.buffer),
                  Bind::Buffer(self.gui_colours.buffer), Bind::Buffer(self.gui_tiles.buffer), Bind::Buffer(self.gui_coeff.buffer),
                  Bind::Buffer(self.gui_error.buffer)],
                &push, (ew.div_ceil(16), eh.div_ceil(16)));
            gpu::compute_barrier(d, cmd);
        }
        // Resize maps, when the geometry changes (source_resize_prepare).
        let (dw, dh) = (p.placement[2], p.placement[3]);
        if p.pack == plan::PACK_RESIZED {
            let key = [w, h, dw, dh, p.top_left];
            if self.resize_key != Some(key) {
                unsafe { d.device.cmd_bind_pipeline(cmd, vk::PipelineBindPoint::COMPUTE, self.resize_prepare.pipeline) };
                self.push.bind(cmd, &self.resize_prepare, &[Bind::Buffer(self.ymap.buffer)]);
                gpu::push_constants(d, cmd, &self.resize_prepare, &ResizePush { source: [w, h], dest: [dw, dh], top_left: p.top_left });
                unsafe { d.device.cmd_dispatch(cmd, dh.div_ceil(64), 1, 1) };
                gpu::compute_barrier(d, cmd);
                self.resize_key = Some(key);
            }
        }

        // Pack into the output.
        let pack = &self.pack[((source * 2 + p.overlay_visible) * 3 + p.pack) as usize];
        let fused_tables = if source == 1 { Bind::Range(self.tables.buffer, T_SINGLE, 6144) } else { Bind::Range(self.tables.buffer, T_MAPPING, 2048) };
        unsafe { d.device.cmd_bind_pipeline(cmd, vk::PipelineBindPoint::COMPUTE, pack.pipeline) };
        self.push.bind(
            cmd,
            pack,
            &[
                Bind::Buffer(self.planes[0].buffer),
                Bind::Buffer(self.planes[1].buffer),
                Bind::Buffer(self.planes[2].buffer),
                Bind::Buffer(self.packets.buffer),
                Bind::Buffer(out_buffer),
                Bind::Buffer(self.ymap.buffer),
                Bind::Buffer(self.gui_colours.buffer),
                Bind::Buffer(self.gui_tiles.buffer),
                Bind::Buffer(self.gui_error.buffer),
                Bind::Sampled(bl.luma.view, self.sampler),
                Bind::Sampled(bl.chroma.view, self.sampler),
                Bind::Sampled(el_view, self.sampler),
                fused_tables,
                Bind::Range(self.tables.buffer, T_RESIDUAL, 4096),
                Bind::Buffer(self.error.buffer),
            ],
        );
        let push = PackPush {
            active: p.active,
            black: p.black,
            placement: p.placement,
            w: CANVAS_W,
            h: CANVAS_H,
            stride_words: out_stride / 4,
            packet_count: p.packet_count,
            top_left: p.top_left,
            source_w: p.source_w,
            source_h: p.source_h,
            nearest: p.nearest,
        };
        gpu::push_constants(d, cmd, pack, &push);
        unsafe { d.device.cmd_dispatch(cmd, (CANVAS_W / 4).div_ceil(32), (CANVAS_H / 2).div_ceil(2), 1) };
        if let Some(q) = self.profile {
            unsafe { d.device.cmd_write_timestamp2(cmd, vk::PipelineStageFlags2::COMPUTE_SHADER, q, 2) };
        }
        gpu::foreign_buffer(d, cmd, out_buffer, false);
        gpu::compute_to_host(d, cmd);
        unsafe { d.device.end_command_buffer(cmd)? };
        let ticket = self.ticket + 1;
        let mut wait_infos: Vec<_> = waits
            .iter()
            .map(|&s| vk::SemaphoreSubmitInfo::default().semaphore(s).stage_mask(vk::PipelineStageFlags2::COMPUTE_SHADER))
            .collect();
        if let (Some(rel), true) = (self.release, f.release_wait > 0) {
            wait_infos.push(vk::SemaphoreSubmitInfo::default().semaphore(rel).value(f.release_wait).stage_mask(vk::PipelineStageFlags2::COMPUTE_SHADER));
        }
        let signal_infos = [
            vk::SemaphoreSubmitInfo::default().semaphore(self.timeline).value(ticket).stage_mask(vk::PipelineStageFlags2::ALL_COMMANDS),
            vk::SemaphoreSubmitInfo::default().semaphore(self.ring[ci].done).stage_mask(vk::PipelineStageFlags2::ALL_COMMANDS),
        ];
        let cmds = [vk::CommandBufferSubmitInfo::default().command_buffer(cmd)];
        let submit = [vk::SubmitInfo2::default()
            .wait_semaphore_infos(&wait_infos)
            .command_buffer_infos(&cmds)
            .signal_semaphore_infos(&signal_infos)];
        unsafe { d.device.queue_submit2(d.queue, &submit, vk::Fence::null())? };
        self.ticket = ticket;
        // The frame's fence on the output dmabuf: the compositor (KWin waits
        // for a committed buffer's implicit fences) and KMS see it as written
        // only when it is.
        let fence = crate::interop::sync::sync_file_from_semaphore(d, self.ring[ci].done)?;
        let r = crate::interop::sync::import_sync_file(out_fd, fence, crate::interop::sync::DMA_BUF_SYNC_WRITE);
        unsafe { libc::close(fence) };
        if r.is_err() {
            // An older kernel: the caller has to wait for the ticket before committing.
            self.implicit_failed = true;
        }
        Ok(ticket)
    }
}

impl Engine {
    fn dispatch<T: Copy>(&self, cmd: vk::CommandBuffer, pipe: &Pipeline, binds: &[Bind], push: &T, groups: (u32, u32)) {
        let d = &self.d;
        unsafe { d.device.cmd_bind_pipeline(cmd, vk::PipelineBindPoint::COMPUTE, pipe.pipeline) };
        self.push.bind(cmd, pipe, binds);
        gpu::push_constants(d, cmd, pipe, push);
        unsafe { d.device.cmd_dispatch(cmd, groups.0.max(1), groups.1.max(1), 1) };
    }

    /// reconstruct_impl's direct route for a half-size EL (opencl_backend.c),
    /// kernel for kernel: vertical_pair, luma_phase_guide, phase_vertical_uv,
    /// then mmr64_lut_dual_horizontal (dual MMR) or scale_horizontal +
    /// the table add (polynomial chroma). Luma rows [first, last).
    fn record_fel(&self, cmd: vk::CommandBuffer, p: &Plan, bl: &va::SurfaceImport, el: &va::SurfaceImport, first: u32, last: u32) {
        let (w, h) = (p.width, p.height);
        let (cw, ch) = (w / 2, h / 2);
        let t = self.tables.buffer;
        let fb = |i: usize| Bind::Buffer(self.fel_buffers[i].buffer);
        let err = || Bind::Buffer(self.error.buffer);
        let quarter = (cw * ch * 2) as u64;
        let f = &self.fel;
        let barrier = || gpu::compute_barrier(&self.d, cmd);
        // c = 0: the EL luma upsampled vertically (EL rows [first/2, last/2)).
        self.dispatch(cmd, &f.vertical_pair, &[Bind::Sampled(el.luma.view, self.sampler), fb(F_V), err()],
            &[cw, ch, 0u32, p.nearest, first / 2], (cw.div_ceil(16), ((last - first) / 2).div_ceil(8)));
        barrier();
        // luma, BL chroma phase and guide per 2x2 block.
        self.dispatch(cmd, &f.luma_phase_guide,
            &[Bind::Sampled(bl.luma.view, self.sampler), Bind::Sampled(bl.chroma.view, self.sampler), fb(F_V),
              Bind::Range(t, T_MAPPING, 2048), Bind::Range(t, T_RESIDUAL, 4096), Bind::Buffer(self.planes[0].buffer),
              fb(F_BP), fb(F_G), err()],
            &[w, h, p.chroma_phase, p.nearest, first / 2], ((w / 2).div_ceil(16), ((last - first) / 2).div_ceil(8)));
        // c = 1: the EL chroma, phase + vertical (overwrites V: the luma pass is done).
        barrier();
        self.dispatch(cmd, &f.phase_vertical_uv, &[Bind::Sampled(el.chroma.view, self.sampler), fb(F_V), fb(F_VP), err()],
            &[cw / 2, ch / 2, p.chroma_phase, p.nearest, first / 4], ((cw / 2).div_ceil(16), ((last - first) / 4).div_ceil(8)));
        barrier();
        let rows = (last - first) / 2;
        if p.dual != 0 {
            self.dispatch(cmd, &f.mmr_dual_horizontal,
                &[fb(F_G), fb(F_BP), fb(F_V), fb(F_VP), Bind::Range(t, T_PARAMS, 768), Bind::Range(t, T_RESIDUAL, 12288),
                  Bind::Buffer(self.planes[1].buffer), Bind::Buffer(self.planes[2].buffer), Bind::Range(t, T_LUT, 49152),
                  // unused bindings 9, 10 (kept for a stable layout), 11 error
                  fb(F_ES), fb(F_ES), err()],
                &[cw, ch, p.nearest, first / 2], ((cw / 2).div_ceil(64), rows));
        } else {
            for c in 0..2u32 {
                let src = if c == 0 { fb(F_V) } else { fb(F_VP) };
                let es = Bind::Range(self.fel_buffers[F_ES].buffer, c as u64 * quarter, quarter);
                self.dispatch(cmd, &f.scale_horizontal, &[src, es, err()], &[cw, ch, p.nearest, first / 2], (cw.div_ceil(64), rows));
            }
            barrier();
            self.record_chroma(cmd, p, first, last);
        }
    }

    /// The chroma of a non-dual frame, channel by channel, from the BL phase
    /// planes, the guide and the scaled EL planes (ES): the polynomial table
    /// add, or mmr64_lut / mmr96 / mmr (128), as reconstruct_impl picks them.
    fn record_chroma(&self, cmd: vk::CommandBuffer, p: &Plan, first: u32, last: u32) {
        let (cw, ch) = (p.width / 2, p.height / 2);
        let quarter = (cw * ch * 2) as u64;
        let t = self.tables.buffer;
        let fb = |i: usize| Bind::Buffer(self.fel_buffers[i].buffer);
        let err = || Bind::Buffer(self.error.buffer);
        let rows = (last - first) / 2;
        for c in 0..2u32 {
            let es = Bind::Range(self.fel_buffers[F_ES].buffer, c as u64 * quarter, quarter);
            let out = Bind::Buffer(self.planes[1 + c as usize].buffer);
            let kind = p.chroma_kind[c as usize];
            if kind == plan::CHROMA_POLY {
                self.dispatch(cmd, &self.fel.table_add,
                    &[Bind::Range(self.fel_buffers[F_BP].buffer, c as u64 * quarter, quarter), es,
                      Bind::Range(t, T_CHROMA_MAPPING + c as u64 * 2048, 2048),
                      Bind::Range(t, T_RESIDUAL + (c as u64 + 1) * 4096, 4096), out, err()],
                    &[cw, ch, first / 2], (cw.div_ceil(64), rows));
            } else {
                let k = match kind { plan::CHROMA_MMR64_LUT => 0, plan::CHROMA_MMR96 => 1, _ => 2 };
                self.dispatch(cmd, &self.fel.mmr_single[k],
                    &[fb(F_G), fb(F_BP), es, Bind::Range(t, T_PARAMS + c as u64 * 384, 384),
                      Bind::Range(t, T_RESIDUAL + (c as u64 + 1) * 4096, 4096), out,
                      Bind::Range(t, T_LUT + c as u64 * 24576, 24576), err()],
                    &[cw, ch, first / 2], (cw.div_ceil(64), rows));
            }
        }
    }

    /// reconstruct_impl's direct route for a full-size EL: phase_guide,
    /// luma_equal, phase on each EL chroma channel, then the chroma.
    fn record_fel_equal(&self, cmd: vk::CommandBuffer, p: &Plan, bl: &va::SurfaceImport, el: &va::SurfaceImport, first: u32, last: u32) {
        let (w, h) = (p.width, p.height);
        let (cw, ch) = (w / 2, h / 2);
        let quarter = (cw * ch * 2) as u64;
        let t = self.tables.buffer;
        let fb = |i: usize| Bind::Buffer(self.fel_buffers[i].buffer);
        let err = || Bind::Buffer(self.error.buffer);
        let f = &self.fel;
        let s = self.sampler;
        let rows = (last - first) / 2;
        self.dispatch(cmd, &f.equal[2],
            &[Bind::Sampled(bl.luma.view, s), Bind::Sampled(bl.chroma.view, s), Bind::Range(t, T_MAPPING, 2048),
              Bind::Range(t, T_RESIDUAL, 4096), fb(F_BP), fb(F_G), err(), err()],
            &[w, h, p.chroma_phase, 0u32, first / 2], (cw.div_ceil(16), rows.div_ceil(8)));
        self.dispatch(cmd, &f.equal[0],
            &[Bind::Sampled(bl.luma.view, s), Bind::Sampled(el.luma.view, s), Bind::Range(t, T_MAPPING, 2048),
              Bind::Range(t, T_RESIDUAL, 4096), Bind::Buffer(self.planes[0].buffer), fb(F_G), err(), err()],
            &[w, h, p.chroma_phase, 0u32, first], (w.div_ceil(16), (last - first).div_ceil(8)));
        for c in 0..2u32 {
            self.dispatch(cmd, &f.equal[1],
                &[Bind::Sampled(el.chroma.view, s), Bind::Sampled(el.chroma.view, s), Bind::Range(t, T_MAPPING, 2048),
                  Bind::Range(t, T_RESIDUAL, 4096), Bind::Range(self.fel_buffers[F_ES].buffer, c as u64 * quarter, quarter),
                  fb(F_G), err(), err()],
                &[cw, ch, p.chroma_phase, c, first / 2], (cw.div_ceil(16), rows.div_ceil(8)));
        }
        gpu::compute_barrier(&self.d, cmd);
        if p.dual != 0 {
            let es = |c: u64| Bind::Range(self.fel_buffers[F_ES].buffer, c * quarter, quarter);
            self.dispatch(cmd, &f.mmr_dual,
                &[fb(F_G), fb(F_BP), es(0), es(1), Bind::Range(t, T_PARAMS, 768), Bind::Range(t, T_RESIDUAL, 12288),
                  Bind::Buffer(self.planes[1].buffer), Bind::Buffer(self.planes[2].buffer), Bind::Range(t, T_LUT, 49152),
                  fb(F_ES), fb(F_ES), err()],
                &[cw, ch, 0u32, first / 2], ((cw / 2).div_ceil(64), rows));
        } else {
            self.record_chroma(cmd, p, first, last);
        }
    }
}

impl Drop for Engine {
    fn drop(&mut self) {
        unsafe {
            let _ = self.d.device.device_wait_idle();
        }
        let d = &self.d;
        for (_, s) in self.surfaces.drain() {
            s.destroy(d);
        }
        for o in self.outputs.drain(..).flatten() {
            o.buffer.destroy(d);
        }
        for o in self.outputs.iter().flatten() {
            unsafe { libc::close(o.fd) };
        }
        for c in &self.ring {
            unsafe {
                d.device.destroy_command_pool(c.pool, None);
                for s in c.decode {
                    d.device.destroy_semaphore(s, None);
                }
                d.device.destroy_semaphore(c.done, None);
            }
            c.tables.destroy(d);
            c.packets.destroy(d);
            c.error.destroy(d);
            c.gui_coeff.destroy(d);
            c.gui_error.destroy(d);
        }
        unsafe { d.device.destroy_semaphore(self.timeline, None) };
        if let Some(r) = self.release {
            unsafe { d.device.destroy_semaphore(r, None) };
        }
        self.shot.destroy(d);
        self.overlay.destroy(d);
        self.gui_colours.destroy(d);
        self.gui_tiles.destroy(d);
        self.gui_keys.destroy(d);
        for p in &self.overlay_prepare {
            p.destroy(d);
        }
        unsafe { d.device.destroy_sampler(self.linear, None) };
        self.sources.destroy(d);
        self.gui_coeff.destroy(d);
        self.gui_error.destroy(d);
        self.error.destroy(d);
        self.packets.destroy(d);
        self.tables.destroy(d);
        self.ymap.destroy(d);
        for p in &self.planes {
            p.destroy(d);
        }
        self.resize_prepare.destroy(d);
        for p in &self.pack {
            p.destroy(d);
        }
        self.single.destroy(d);
        self.fel_chroma.destroy(d);
        if let Some(q) = self.profile {
            unsafe { d.device.destroy_query_pool(q, None) };
        }
        for p in [&self.fel.vertical_pair, &self.fel.luma_phase_guide, &self.fel.phase_vertical_uv,
                  &self.fel.mmr_dual_horizontal, &self.fel.scale_horizontal, &self.fel.table_add, &self.fel.mmr_dual] {
            p.destroy(d);
        }
        for p in self.fel.mmr_single.iter().chain(self.fel.equal.iter()).chain(self.fel.piecewise.iter()) {
            p.destroy(d);
        }
        for b in &self.fel_buffers {
            b.destroy(d);
        }
        unsafe { d.device.destroy_sampler(self.sampler, None) };
    }
}
