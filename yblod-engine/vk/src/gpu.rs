//! Small Vulkan helpers: compute pipelines from the built-in SPIR-V, host
//! buffers, descriptor writes and one-shot command submission.

use crate::device::{Device, Error, Result};
use ash::vk;

include!(concat!(env!("OUT_DIR"), "/shaders.rs"));

pub fn spirv(name: &str) -> Result<Vec<u32>> {
    let bytes = SHADERS.iter().find(|(n, _)| *n == name).map(|(_, b)| *b).ok_or(Error::Missing("a shader"))?;
    Ok(bytes.as_chunks::<4>().0.iter().map(|c| u32::from_le_bytes(*c)).collect())
}

// Private line protocol for the isolated preparation helper; no C ABI change.
// Thread local: concurrent engines cannot mix progress counts.
thread_local! { static PREPARE: std::cell::Cell<Option<(u32, u32)>> = const { std::cell::Cell::new(None) }; }
// (done, total, report): pipelines are always counted, so a wrong total shows
// in any build; only DVVK_PREPARE_PROGRESS reports and enforces it.
thread_local! { static PREPARE_REPORT: std::cell::Cell<bool> = const { std::cell::Cell::new(false) }; }
pub(crate) fn prepare_begin(report: bool, total: u32) {
    PREPARE.with(|p| p.set(Some((0, total))));
    PREPARE_REPORT.with(|r| r.set(report));
}
pub(crate) fn prepare_end() -> Result<()> {
    let report = PREPARE_REPORT.with(|r| r.replace(false));
    PREPARE.with(|p| match p.replace(None) {
        Some((done, total)) if done != total => {
            eprintln!("dv-engine-vk: created {done} pipelines, expected {total}");
            if report {
                Err(Error::Unsupported("preparation pipeline count changed".into()))
            } else {
                Ok(())
            }
        }
        _ => Ok(()),
    })
}
fn prepare_completed() {
    PREPARE.with(|p| {
        if let Some((done, total)) = p.get() {
            p.set(Some((done + 1, total)));
            if !PREPARE_REPORT.with(|r| r.get()) {
                return;
            }
            // Only successful vkCreateComputePipelines results reach this point.
            // A disappearing progress reader must not panic/abort past construction
            // rollback. The supervisor also requires READY plus successful exit.
            use std::io::Write;
            let _ = writeln!(std::io::stdout().lock(), "DVVK_PREPARE {} {}", done + 1, total);
        }
    });
}

pub struct Pipeline {
    pub set_layout: vk::DescriptorSetLayout,
    pub layout: vk::PipelineLayout,
    pub pipeline: vk::Pipeline,
    pub bindings: Vec<vk::DescriptorType>,
}

impl Pipeline {
    /// `bindings[i]` is binding i of set 0; `spec` are (id, u32 value).
    pub fn new(
        d: &Device,
        shader: &str,
        bindings: &[vk::DescriptorType],
        push_bytes: u32,
        spec: &[(u32, u32)],
    ) -> Result<Self> {
        Self::new_impl(d, shader, bindings, push_bytes, spec, false)
    }

    pub fn new_deferred(
        d: &Device,
        shader: &str,
        bindings: &[vk::DescriptorType],
        push_bytes: u32,
        spec: &[(u32, u32)],
    ) -> Result<Self> {
        Self::new_impl(d, shader, bindings, push_bytes, spec, true)
    }

    fn new_impl(
        d: &Device,
        shader: &str,
        bindings: &[vk::DescriptorType],
        push_bytes: u32,
        spec: &[(u32, u32)],
        deferred: bool,
    ) -> Result<Self> {
        let creation_start = std::time::Instant::now();
        if bindings.len() > MAX_BINDINGS {
            return Err(Error::Unsupported(format!("{shader}: {} bindings", bindings.len())));
        }
        let code = spirv(shader)?;
        let module =
            unsafe { d.device.create_shader_module(&vk::ShaderModuleCreateInfo::default().code(&code), None) }?;
        let b: Vec<_> = bindings
            .iter()
            .enumerate()
            .map(|(i, t)| {
                vk::DescriptorSetLayoutBinding::default()
                    .binding(i as u32)
                    .descriptor_type(*t)
                    .descriptor_count(1)
                    .stage_flags(vk::ShaderStageFlags::COMPUTE)
            })
            .collect();
        let set_layout = if deferred && crate::fault::hit("lazy-set-layout") {
            Err(vk::Result::ERROR_UNKNOWN)
        } else {
            unsafe {
                d.device.create_descriptor_set_layout(
                    &vk::DescriptorSetLayoutCreateInfo::default()
                        .flags(vk::DescriptorSetLayoutCreateFlags::PUSH_DESCRIPTOR_KHR)
                        .bindings(&b),
                    None,
                )
            }
        };
        let set_layout = match set_layout {
            Ok(v) => v,
            Err(e) => {
                unsafe { d.device.destroy_shader_module(module, None) };
                return Err(Error::Vk(e));
            }
        };
        let ranges = [vk::PushConstantRange::default()
            .stage_flags(vk::ShaderStageFlags::COMPUTE)
            .offset(0)
            .size(push_bytes.max(4))];
        let layouts = [set_layout];
        let layout = if deferred && crate::fault::hit("lazy-pipeline-layout") {
            Err(vk::Result::ERROR_UNKNOWN)
        } else {
            unsafe {
                d.device.create_pipeline_layout(
                    &vk::PipelineLayoutCreateInfo::default().set_layouts(&layouts).push_constant_ranges(&ranges),
                    None,
                )
            }
        };
        let layout = match layout {
            Ok(v) => v,
            Err(e) => {
                unsafe {
                    d.device.destroy_descriptor_set_layout(set_layout, None);
                    d.device.destroy_shader_module(module, None);
                }
                return Err(Error::Vk(e));
            }
        };
        let entries: Vec<_> = spec
            .iter()
            .enumerate()
            .map(|(i, (id, _))| vk::SpecializationMapEntry { constant_id: *id, offset: 4 * i as u32, size: 4 })
            .collect();
        let data: Vec<u8> = spec.iter().flat_map(|(_, v)| v.to_le_bytes()).collect();
        let spec_info = vk::SpecializationInfo::default().map_entries(&entries).data(&data);
        let subgroup_size = d.subgroup_overrides.get(shader).copied().unwrap_or(d.subgroup_size);
        let mut required =
            vk::PipelineShaderStageRequiredSubgroupSizeCreateInfo::default().required_subgroup_size(subgroup_size);
        let mut stage = vk::PipelineShaderStageCreateInfo::default()
            .stage(vk::ShaderStageFlags::COMPUTE)
            .module(module)
            .name(c"main")
            .specialization_info(&spec_info);
        if subgroup_size != 0 {
            stage = stage.push_next(&mut required);
        }
        let info = [vk::ComputePipelineCreateInfo::default().stage(stage).layout(layout)];
        let pipeline = unsafe { d.device.create_compute_pipelines(d.pipeline_cache, &info, None) };
        unsafe { d.device.destroy_shader_module(module, None) };
        // Vulkan may return live partial pipelines even when creation fails.
        // Exercise that cleanup branch without a driver fault in test builds.
        let pipeline = if deferred && crate::fault::hit("lazy-pipeline-result") {
            match pipeline {
                Ok(partial) => Err((partial, vk::Result::ERROR_UNKNOWN)),
                other => other,
            }
        } else {
            pipeline
        };
        let pipeline = match pipeline {
            Ok(p) => p[0],
            Err((partial, e)) => {
                unsafe {
                    for p in partial {
                        d.device.destroy_pipeline(p, None);
                    }
                    d.device.destroy_pipeline_layout(layout, None);
                    d.device.destroy_descriptor_set_layout(set_layout, None);
                }
                return Err(Error::Vk(e));
            }
        };
        if d.options.pipeline_profile {
            eprintln!(
                "dvvk pipeline: shader={shader} subgroup={subgroup_size} spec={spec:?} creation_ms={:.4}",
                creation_start.elapsed().as_secs_f64() * 1000.0
            );
        }
        prepare_completed();
        Ok(Pipeline { set_layout, layout, pipeline, bindings: bindings.to_vec() })
    }

    pub fn destroy(&self, d: &Device) {
        unsafe {
            d.device.destroy_pipeline(self.pipeline, None);
            d.device.destroy_pipeline_layout(self.layout, None);
            d.device.destroy_descriptor_set_layout(self.set_layout, None);
        }
    }
}

/// The most bindings a pipeline has (the pack: 25). VK_KHR_push_descriptor
/// guarantees maxPushDescriptors >= 32.
pub const MAX_BINDINGS: usize = 32;

/// One resource bound with push descriptors.
pub enum Bind {
    Buffer(vk::Buffer),
    Range(vk::Buffer, u64, u64),
    Image(vk::ImageView),
    Sampled(vk::ImageView, vk::Sampler),
}

pub struct PushDescriptor {
    pub loader: ash::khr::push_descriptor::Device,
}

impl PushDescriptor {
    pub fn new(d: &Device) -> Self {
        PushDescriptor { loader: ash::khr::push_descriptor::Device::new(&d.instance, &d.device) }
    }

    /// Binding i of `p` to binds[i]; on the stack (it runs for every dispatch).
    pub fn bind(&self, cmd: vk::CommandBuffer, p: &Pipeline, binds: &[Bind]) {
        let n = binds.len();
        assert!(n <= MAX_BINDINGS && n <= p.bindings.len(), "{n} bindings");
        let mut buffers = [[vk::DescriptorBufferInfo::default()]; MAX_BINDINGS];
        let mut images = [[vk::DescriptorImageInfo::default()]; MAX_BINDINGS];
        for (i, b) in binds.iter().enumerate() {
            match b {
                Bind::Buffer(buf) => {
                    buffers[i] = [vk::DescriptorBufferInfo { buffer: *buf, offset: 0, range: vk::WHOLE_SIZE }]
                }
                Bind::Range(buf, offset, size) => {
                    buffers[i] = [vk::DescriptorBufferInfo { buffer: *buf, offset: *offset, range: *size }]
                }
                Bind::Image(v) => {
                    images[i] = [vk::DescriptorImageInfo {
                        sampler: vk::Sampler::null(),
                        image_view: *v,
                        image_layout: vk::ImageLayout::GENERAL,
                    }]
                }
                Bind::Sampled(v, s) => {
                    images[i] = [vk::DescriptorImageInfo {
                        sampler: *s,
                        image_view: *v,
                        image_layout: vk::ImageLayout::GENERAL,
                    }]
                }
            }
        }
        let mut writes = [vk::WriteDescriptorSet::default(); MAX_BINDINGS];
        for (i, b) in binds.iter().enumerate() {
            let w = vk::WriteDescriptorSet::default().dst_binding(i as u32).descriptor_type(p.bindings[i]);
            writes[i] = match b {
                Bind::Buffer(_) | Bind::Range(..) => w.buffer_info(&buffers[i]),
                _ => w.image_info(&images[i]),
            };
        }
        unsafe {
            self.loader.cmd_push_descriptor_set(cmd, vk::PipelineBindPoint::COMPUTE, p.layout, 0, &writes[..n]);
        }
    }
}

pub struct HostBuffer {
    pub buffer: vk::Buffer,
    pub memory: vk::DeviceMemory,
    pub ptr: *mut u8,
    pub size: u64,
}

impl HostBuffer {
    pub fn new(d: &Device, size: u64, usage: vk::BufferUsageFlags) -> Result<Self> {
        let buffer = unsafe {
            d.device.create_buffer(
                &vk::BufferCreateInfo::default().size(size).usage(usage).sharing_mode(vk::SharingMode::EXCLUSIVE),
                None,
            )
        }?;
        let mut memory = vk::DeviceMemory::null();
        let mut mapped = false;
        let result = (|| {
            crate::fault::check("construct-host-created")?;
            let req = unsafe { d.device.get_buffer_memory_requirements(buffer) };
            let flags = vk::MemoryPropertyFlags::HOST_VISIBLE | vk::MemoryPropertyFlags::HOST_COHERENT;
            let index = d
                .memory_type(req.memory_type_bits, flags | vk::MemoryPropertyFlags::HOST_CACHED)
                .or_else(|| d.memory_type(req.memory_type_bits, flags))
                .ok_or(Error::Missing("host-visible memory"))?;
            memory = unsafe {
                d.device.allocate_memory(
                    &vk::MemoryAllocateInfo::default().allocation_size(req.size).memory_type_index(index),
                    None,
                )
            }?;
            crate::fault::check("construct-host-allocated")?;
            unsafe { d.device.bind_buffer_memory(buffer, memory, 0) }?;
            let ptr =
                unsafe { d.device.map_memory(memory, 0, vk::WHOLE_SIZE, vk::MemoryMapFlags::empty()) }? as *mut u8;
            mapped = true;
            crate::fault::check("construct-host-mapped")?;
            Ok(HostBuffer { buffer, memory, ptr, size })
        })();
        if result.is_err() {
            unsafe {
                if mapped {
                    d.device.unmap_memory(memory);
                }
                d.device.destroy_buffer(buffer, None);
                d.device.free_memory(memory, None);
            }
        }
        result
    }

    pub fn bytes(&self) -> &[u8] {
        unsafe { std::slice::from_raw_parts(self.ptr, self.size as usize) }
    }

    pub fn bytes_mut(&mut self) -> &mut [u8] {
        unsafe { std::slice::from_raw_parts_mut(self.ptr, self.size as usize) }
    }

    pub fn destroy(&self, d: &Device) {
        unsafe {
            d.device.unmap_memory(self.memory);
            d.device.destroy_buffer(self.buffer, None);
            d.device.free_memory(self.memory, None);
        }
    }
}

pub fn nearest_sampler(d: &Device) -> Result<vk::Sampler> {
    let info = vk::SamplerCreateInfo::default()
        .mag_filter(vk::Filter::NEAREST)
        .min_filter(vk::Filter::NEAREST)
        .mipmap_mode(vk::SamplerMipmapMode::NEAREST)
        .address_mode_u(vk::SamplerAddressMode::CLAMP_TO_EDGE)
        .address_mode_v(vk::SamplerAddressMode::CLAMP_TO_EDGE)
        .address_mode_w(vk::SamplerAddressMode::CLAMP_TO_EDGE)
        .unnormalized_coordinates(false);
    Ok(unsafe { d.device.create_sampler(&info, None) }?)
}

/// Barrier taking imported images from the foreign (external) owner into
/// GENERAL layout, keeping their contents.
pub fn acquire_foreign_images(d: &Device, cmd: vk::CommandBuffer, images: &[vk::Image]) {
    assert!(images.len() <= 4);
    let mut barriers = [vk::ImageMemoryBarrier2::default(); 4];
    for (b, &image) in barriers.iter_mut().zip(images) {
        *b = vk::ImageMemoryBarrier2::default()
            .src_stage_mask(vk::PipelineStageFlags2::NONE)
            .dst_stage_mask(vk::PipelineStageFlags2::COMPUTE_SHADER)
            .dst_access_mask(vk::AccessFlags2::SHADER_READ)
            .old_layout(vk::ImageLayout::GENERAL)
            .new_layout(vk::ImageLayout::GENERAL)
            .src_queue_family_index(vk::QUEUE_FAMILY_FOREIGN_EXT)
            .dst_queue_family_index(d.queue_family)
            .image(image)
            .subresource_range(vk::ImageSubresourceRange {
                aspect_mask: vk::ImageAspectFlags::COLOR,
                base_mip_level: 0,
                level_count: 1,
                base_array_layer: 0,
                layer_count: 1,
            });
    }
    unsafe {
        d.device.cmd_pipeline_barrier2(
            cmd,
            &vk::DependencyInfo::default().image_memory_barriers(&barriers[..images.len()]),
        );
    }
}

/// Compute (and transfer) writes → host reads / other compute reads.
pub fn compute_to_host(d: &Device, cmd: vk::CommandBuffer) {
    let m = [vk::MemoryBarrier2::default()
        .src_stage_mask(vk::PipelineStageFlags2::COMPUTE_SHADER | vk::PipelineStageFlags2::TRANSFER)
        .src_access_mask(vk::AccessFlags2::SHADER_WRITE | vk::AccessFlags2::TRANSFER_WRITE)
        .dst_stage_mask(vk::PipelineStageFlags2::HOST | vk::PipelineStageFlags2::COMPUTE_SHADER)
        .dst_access_mask(vk::AccessFlags2::HOST_READ | vk::AccessFlags2::SHADER_READ)];
    unsafe { d.device.cmd_pipeline_barrier2(cmd, &vk::DependencyInfo::default().memory_barriers(&m)) };
}

/// A command pool with one buffer and a fence, for tests and set-up.
pub struct OneShot {
    pub pool: vk::CommandPool,
    pub cmd: vk::CommandBuffer,
    pub fence: vk::Fence,
}

impl OneShot {
    pub fn new(d: &Device) -> Result<Self> {
        let pool = unsafe {
            d.device.create_command_pool(
                &vk::CommandPoolCreateInfo::default()
                    .queue_family_index(d.queue_family)
                    .flags(vk::CommandPoolCreateFlags::RESET_COMMAND_BUFFER),
                None,
            )
        }?;
        let result = (|| {
            let cmd = unsafe {
                d.device.allocate_command_buffers(
                    &vk::CommandBufferAllocateInfo::default().command_pool(pool).command_buffer_count(1),
                )
            }?[0];
            crate::fault::check("construct-shot-command")?;
            let fence = unsafe { d.device.create_fence(&vk::FenceCreateInfo::default(), None) }?;
            Ok(OneShot { pool, cmd, fence })
        })();
        if result.is_err() {
            unsafe { d.device.destroy_command_pool(pool, None) };
        }
        result
    }

    pub fn begin(&self, d: &Device) -> Result<vk::CommandBuffer> {
        crate::fault::check("construct-shot-begin")?;
        unsafe {
            d.device.reset_command_buffer(self.cmd, vk::CommandBufferResetFlags::empty())?;
            d.device.begin_command_buffer(
                self.cmd,
                &vk::CommandBufferBeginInfo::default().flags(vk::CommandBufferUsageFlags::ONE_TIME_SUBMIT),
            )?;
        }
        Ok(self.cmd)
    }

    /// Ends, submits (waiting on `waits` at compute), signals `signal` if any,
    /// and blocks until done.
    pub fn submit_wait(&self, d: &Device, waits: &[vk::Semaphore], signal: &[vk::Semaphore]) -> Result<()> {
        unsafe {
            d.device.end_command_buffer(self.cmd)?;
            let w: Vec<_> = waits
                .iter()
                .map(|&s| {
                    vk::SemaphoreSubmitInfo::default().semaphore(s).stage_mask(vk::PipelineStageFlags2::COMPUTE_SHADER)
                })
                .collect();
            let sg: Vec<_> = signal
                .iter()
                .map(|&s| {
                    vk::SemaphoreSubmitInfo::default().semaphore(s).stage_mask(vk::PipelineStageFlags2::ALL_COMMANDS)
                })
                .collect();
            let c = [vk::CommandBufferSubmitInfo::default().command_buffer(self.cmd)];
            let submit = [vk::SubmitInfo2::default()
                .wait_semaphore_infos(&w)
                .command_buffer_infos(&c)
                .signal_semaphore_infos(&sg)];
            d.device.queue_submit2(d.queue, &submit, self.fence)?;
            crate::fault::check("construct-shot-wait")?;
            d.device.wait_for_fences(&[self.fence], true, 10_000_000_000)?;
            d.device.reset_fences(&[self.fence])?;
        }
        Ok(())
    }

    pub fn destroy(&self, d: &Device) {
        unsafe {
            d.device.destroy_fence(self.fence, None);
            d.device.destroy_command_pool(self.pool, None);
        }
    }
}

/// A device-local storage buffer.
pub struct DeviceBuffer {
    pub buffer: vk::Buffer,
    pub memory: vk::DeviceMemory,
    pub size: u64,
}

impl DeviceBuffer {
    pub fn new(d: &Device, size: u64) -> Result<Self> {
        let buffer = unsafe {
            d.device.create_buffer(
                &vk::BufferCreateInfo::default()
                    .size(size)
                    .usage(
                        vk::BufferUsageFlags::STORAGE_BUFFER
                            | vk::BufferUsageFlags::TRANSFER_SRC
                            | vk::BufferUsageFlags::TRANSFER_DST
                            | vk::BufferUsageFlags::INDIRECT_BUFFER,
                    )
                    .sharing_mode(vk::SharingMode::EXCLUSIVE),
                None,
            )
        }?;
        let mut memory = vk::DeviceMemory::null();
        let result = (|| {
            crate::fault::check("construct-device-created")?;
            let req = unsafe { d.device.get_buffer_memory_requirements(buffer) };
            let index = d
                .memory_type(req.memory_type_bits, vk::MemoryPropertyFlags::DEVICE_LOCAL)
                .ok_or(Error::Missing("device-local memory"))?;
            memory = unsafe {
                d.device.allocate_memory(
                    &vk::MemoryAllocateInfo::default().allocation_size(req.size).memory_type_index(index),
                    None,
                )
            }?;
            crate::fault::check("construct-device-allocated")?;
            unsafe { d.device.bind_buffer_memory(buffer, memory, 0) }?;
            Ok(DeviceBuffer { buffer, memory, size })
        })();
        if result.is_err() {
            unsafe {
                d.device.destroy_buffer(buffer, None);
                d.device.free_memory(memory, None);
            }
        }
        result
    }

    pub fn destroy(&self, d: &Device) {
        unsafe {
            d.device.destroy_buffer(self.buffer, None);
            d.device.free_memory(self.memory, None);
        }
    }
}

/// Compute writes → compute reads (and transfer).
pub fn compute_barrier(d: &Device, cmd: vk::CommandBuffer) {
    let m = [vk::MemoryBarrier2::default()
        .src_stage_mask(vk::PipelineStageFlags2::COMPUTE_SHADER | vk::PipelineStageFlags2::TRANSFER)
        .src_access_mask(vk::AccessFlags2::SHADER_WRITE | vk::AccessFlags2::TRANSFER_WRITE)
        .dst_stage_mask(vk::PipelineStageFlags2::COMPUTE_SHADER | vk::PipelineStageFlags2::TRANSFER)
        .dst_access_mask(
            vk::AccessFlags2::SHADER_READ | vk::AccessFlags2::SHADER_WRITE | vk::AccessFlags2::TRANSFER_READ,
        )];
    unsafe { d.device.cmd_pipeline_barrier2(cmd, &vk::DependencyInfo::default().memory_barriers(&m)) };
}

/// compute_barrier with indirect dispatch arguments (map_fixup's, written
/// by the pack, reset by a transfer) on both sides.
pub fn indirect_barrier(d: &Device, cmd: vk::CommandBuffer) {
    let stages = vk::PipelineStageFlags2::COMPUTE_SHADER
        | vk::PipelineStageFlags2::TRANSFER
        | vk::PipelineStageFlags2::DRAW_INDIRECT;
    let m = [vk::MemoryBarrier2::default()
        .src_stage_mask(stages)
        .src_access_mask(vk::AccessFlags2::SHADER_WRITE | vk::AccessFlags2::TRANSFER_WRITE)
        .dst_stage_mask(stages)
        .dst_access_mask(
            vk::AccessFlags2::SHADER_READ
                | vk::AccessFlags2::SHADER_WRITE
                | vk::AccessFlags2::TRANSFER_WRITE
                | vk::AccessFlags2::INDIRECT_COMMAND_READ,
        )];
    unsafe { d.device.cmd_pipeline_barrier2(cmd, &vk::DependencyInfo::default().memory_barriers(&m)) };
}

/// Ownership of an external buffer: from the foreign owner (`acquire`) or back to it.
pub fn foreign_buffer(d: &Device, cmd: vk::CommandBuffer, buffer: vk::Buffer, acquire: bool) {
    let b = vk::BufferMemoryBarrier2::default().buffer(buffer).offset(0).size(vk::WHOLE_SIZE);
    let b = if acquire {
        b.src_queue_family_index(vk::QUEUE_FAMILY_FOREIGN_EXT)
            .dst_queue_family_index(d.queue_family)
            .dst_stage_mask(vk::PipelineStageFlags2::COMPUTE_SHADER)
            .dst_access_mask(vk::AccessFlags2::SHADER_WRITE)
    } else {
        b.src_queue_family_index(d.queue_family)
            .dst_queue_family_index(vk::QUEUE_FAMILY_FOREIGN_EXT)
            .src_stage_mask(vk::PipelineStageFlags2::COMPUTE_SHADER)
            .src_access_mask(vk::AccessFlags2::SHADER_WRITE)
    };
    let bs = [b];
    unsafe { d.device.cmd_pipeline_barrier2(cmd, &vk::DependencyInfo::default().buffer_memory_barriers(&bs)) };
}

pub fn push_constants<T: Copy>(d: &Device, cmd: vk::CommandBuffer, p: &Pipeline, value: &T) {
    let bytes = unsafe { std::slice::from_raw_parts(value as *const T as *const u8, std::mem::size_of::<T>()) };
    unsafe { d.device.cmd_push_constants(cmd, p.layout, vk::ShaderStageFlags::COMPUTE, 0, bytes) };
}

/// A small device image the host fills (Kodi's GUI LUTs for CB1's overlay):
/// written through a staging buffer, kept in GENERAL layout for sampling.
pub struct SampledImage {
    pub image: vk::Image,
    pub memory: vk::DeviceMemory,
    pub view: vk::ImageView,
}

impl SampledImage {
    pub fn new(d: &Device, format: vk::Format, width: u32, height: u32) -> Result<Self> {
        let info = vk::ImageCreateInfo::default()
            .image_type(vk::ImageType::TYPE_2D)
            .format(format)
            .extent(vk::Extent3D { width, height, depth: 1 })
            .mip_levels(1)
            .array_layers(1)
            .samples(vk::SampleCountFlags::TYPE_1)
            .tiling(vk::ImageTiling::OPTIMAL)
            .usage(vk::ImageUsageFlags::SAMPLED | vk::ImageUsageFlags::TRANSFER_DST)
            .sharing_mode(vk::SharingMode::EXCLUSIVE)
            .initial_layout(vk::ImageLayout::UNDEFINED);
        let image = unsafe { d.device.create_image(&info, None) }?;
        let mut memory = vk::DeviceMemory::null();
        let mut view = vk::ImageView::null();
        let result = (|| {
            crate::fault::check("construct-image-created")?;
            let req = unsafe { d.device.get_image_memory_requirements(image) };
            let index = d
                .memory_type(req.memory_type_bits, vk::MemoryPropertyFlags::DEVICE_LOCAL)
                .ok_or(Error::Missing("device-local memory"))?;
            memory = unsafe {
                d.device.allocate_memory(
                    &vk::MemoryAllocateInfo::default().allocation_size(req.size).memory_type_index(index),
                    None,
                )
            }?;
            crate::fault::check("construct-image-allocated")?;
            unsafe { d.device.bind_image_memory(image, memory, 0) }?;
            view = unsafe {
                d.device.create_image_view(
                    &vk::ImageViewCreateInfo::default()
                        .image(image)
                        .view_type(vk::ImageViewType::TYPE_2D)
                        .format(format)
                        .subresource_range(color_range()),
                    None,
                )
            }?;
            crate::fault::check("construct-image-view")?;
            Ok(SampledImage { image, memory, view })
        })();
        if result.is_err() {
            unsafe {
                d.device.destroy_image_view(view, None);
                d.device.destroy_image(image, None);
                d.device.free_memory(memory, None);
            }
        }
        result
    }

    /// Replaces the whole image with `data` (tightly packed rows) and waits.
    /// The caller makes sure no frame in flight samples it.
    pub fn upload(&self, d: &Device, shot: &OneShot, data: &[u8], width: u32, height: u32) -> Result<()> {
        let mut staging = HostBuffer::new(d, data.len() as u64, vk::BufferUsageFlags::TRANSFER_SRC)?;
        staging.bytes_mut()[..data.len()].copy_from_slice(data);
        let cmd = match shot.begin(d) {
            Ok(cmd) => cmd,
            Err(e) => {
                staging.destroy(d);
                return Err(e);
            }
        };
        let to_transfer = [vk::ImageMemoryBarrier2::default()
            .src_stage_mask(vk::PipelineStageFlags2::COMPUTE_SHADER)
            .dst_stage_mask(vk::PipelineStageFlags2::TRANSFER)
            .dst_access_mask(vk::AccessFlags2::TRANSFER_WRITE)
            .old_layout(vk::ImageLayout::UNDEFINED)
            .new_layout(vk::ImageLayout::TRANSFER_DST_OPTIMAL)
            .image(self.image)
            .subresource_range(color_range())];
        let region = [vk::BufferImageCopy::default()
            .image_subresource(vk::ImageSubresourceLayers {
                aspect_mask: vk::ImageAspectFlags::COLOR,
                mip_level: 0,
                base_array_layer: 0,
                layer_count: 1,
            })
            .image_extent(vk::Extent3D { width, height, depth: 1 })];
        let to_shader = [vk::ImageMemoryBarrier2::default()
            .src_stage_mask(vk::PipelineStageFlags2::TRANSFER)
            .src_access_mask(vk::AccessFlags2::TRANSFER_WRITE)
            .dst_stage_mask(vk::PipelineStageFlags2::COMPUTE_SHADER)
            .dst_access_mask(vk::AccessFlags2::SHADER_READ)
            .old_layout(vk::ImageLayout::TRANSFER_DST_OPTIMAL)
            .new_layout(vk::ImageLayout::GENERAL)
            .image(self.image)
            .subresource_range(color_range())];
        unsafe {
            d.device.cmd_pipeline_barrier2(cmd, &vk::DependencyInfo::default().image_memory_barriers(&to_transfer));
            d.device.cmd_copy_buffer_to_image(
                cmd,
                staging.buffer,
                self.image,
                vk::ImageLayout::TRANSFER_DST_OPTIMAL,
                &region,
            );
            d.device.cmd_pipeline_barrier2(cmd, &vk::DependencyInfo::default().image_memory_barriers(&to_shader));
        }
        let result = shot.submit_wait(d, &[], &[]);
        // A failed wait does not prove the staging buffer is no longer in use.
        // Preserve fail-stop if idle cannot be established; never unwind/drop it.
        if result.is_err() {
            d.require_idle();
        }
        staging.destroy(d);
        result
    }

    pub fn destroy(&self, d: &Device) {
        unsafe {
            d.device.destroy_image_view(self.view, None);
            d.device.destroy_image(self.image, None);
            d.device.free_memory(self.memory, None);
        }
    }
}

/// The output mapping's 3D LUT (map_bake.comp): RGBA16 UNORM, n^3, sampled
/// with trilinear filtering by the pack; written by a buffer copy (no
/// storage-image format feature needed), always in GENERAL layout after the
/// first copy (`ready`). Also SDR output's gamut LUT (`size` then not a cube).
pub struct Lut3d {
    pub image: vk::Image,
    pub memory: vk::DeviceMemory,
    pub view: vk::ImageView,
    pub n: u32,
    pub size: [u32; 3],
    pub ready: bool,
}

impl Lut3d {
    pub fn new(d: &Device, n: u32) -> Result<Self> {
        Self::new_sized(d, [n, n, n])
    }

    pub fn new_sized(d: &Device, size: [u32; 3]) -> Result<Self> {
        let n = size[0];
        let format = vk::Format::R16G16B16A16_UNORM;
        let info = vk::ImageCreateInfo::default()
            .image_type(vk::ImageType::TYPE_3D)
            .format(format)
            .extent(vk::Extent3D { width: size[0], height: size[1], depth: size[2] })
            .mip_levels(1)
            .array_layers(1)
            .samples(vk::SampleCountFlags::TYPE_1)
            .tiling(vk::ImageTiling::OPTIMAL)
            .usage(vk::ImageUsageFlags::SAMPLED | vk::ImageUsageFlags::TRANSFER_DST)
            .sharing_mode(vk::SharingMode::EXCLUSIVE)
            .initial_layout(vk::ImageLayout::UNDEFINED);
        let image = unsafe { d.device.create_image(&info, None) }?;
        let mut memory = vk::DeviceMemory::null();
        let mut view = vk::ImageView::null();
        let result = (|| {
            let req = unsafe { d.device.get_image_memory_requirements(image) };
            let index = d
                .memory_type(req.memory_type_bits, vk::MemoryPropertyFlags::DEVICE_LOCAL)
                .ok_or(Error::Missing("device-local memory"))?;
            memory = unsafe {
                d.device.allocate_memory(
                    &vk::MemoryAllocateInfo::default().allocation_size(req.size).memory_type_index(index),
                    None,
                )
            }?;
            unsafe { d.device.bind_image_memory(image, memory, 0) }?;
            view = unsafe {
                d.device.create_image_view(
                    &vk::ImageViewCreateInfo::default()
                        .image(image)
                        .view_type(vk::ImageViewType::TYPE_3D)
                        .format(format)
                        .subresource_range(color_range()),
                    None,
                )
            }?;
            Ok(Lut3d { image, memory, view, n, size, ready: false })
        })();
        if result.is_err() {
            unsafe {
                d.device.destroy_image_view(view, None);
                d.device.destroy_image(image, None);
                d.device.free_memory(memory, None);
            }
        }
        result
    }

    /// Records the copy of `nodes` (the image's RGBA16 texels, x fastest,
    /// from byte `offset`) into the image, between the compute work before
    /// and after it.
    pub fn record_copy(&mut self, d: &Device, cmd: vk::CommandBuffer, nodes: vk::Buffer, offset: u64) {
        let before = [vk::ImageMemoryBarrier2::default()
            .src_stage_mask(vk::PipelineStageFlags2::COMPUTE_SHADER)
            .src_access_mask(vk::AccessFlags2::SHADER_READ)
            .dst_stage_mask(vk::PipelineStageFlags2::TRANSFER)
            .dst_access_mask(vk::AccessFlags2::TRANSFER_WRITE)
            .old_layout(if self.ready { vk::ImageLayout::GENERAL } else { vk::ImageLayout::UNDEFINED })
            .new_layout(vk::ImageLayout::GENERAL)
            .image(self.image)
            .subresource_range(color_range())];
        let buffer_ready = [vk::MemoryBarrier2::default()
            .src_stage_mask(vk::PipelineStageFlags2::COMPUTE_SHADER)
            .src_access_mask(vk::AccessFlags2::SHADER_WRITE)
            .dst_stage_mask(vk::PipelineStageFlags2::TRANSFER)
            .dst_access_mask(vk::AccessFlags2::TRANSFER_READ)];
        let region = [vk::BufferImageCopy::default()
            .buffer_offset(offset)
            .image_subresource(vk::ImageSubresourceLayers {
                aspect_mask: vk::ImageAspectFlags::COLOR,
                mip_level: 0,
                base_array_layer: 0,
                layer_count: 1,
            })
            .image_extent(vk::Extent3D { width: self.size[0], height: self.size[1], depth: self.size[2] })];
        let after = [vk::ImageMemoryBarrier2::default()
            .src_stage_mask(vk::PipelineStageFlags2::TRANSFER)
            .src_access_mask(vk::AccessFlags2::TRANSFER_WRITE)
            .dst_stage_mask(vk::PipelineStageFlags2::COMPUTE_SHADER)
            .dst_access_mask(vk::AccessFlags2::SHADER_READ)
            .old_layout(vk::ImageLayout::GENERAL)
            .new_layout(vk::ImageLayout::GENERAL)
            .image(self.image)
            .subresource_range(color_range())];
        unsafe {
            d.device.cmd_pipeline_barrier2(
                cmd,
                &vk::DependencyInfo::default().memory_barriers(&buffer_ready).image_memory_barriers(&before),
            );
            d.device.cmd_copy_buffer_to_image(cmd, nodes, self.image, vk::ImageLayout::GENERAL, &region);
            d.device.cmd_pipeline_barrier2(cmd, &vk::DependencyInfo::default().image_memory_barriers(&after));
        }
        self.ready = true;
    }

    /// Before its first copy the image is UNDEFINED: a frame that samples it
    /// without a bake (the DV tunnel binds it unused) moves it to GENERAL.
    pub fn record_init(&mut self, d: &Device, cmd: vk::CommandBuffer) {
        if self.ready {
            return;
        }
        let b = [vk::ImageMemoryBarrier2::default()
            .dst_stage_mask(vk::PipelineStageFlags2::COMPUTE_SHADER)
            .dst_access_mask(vk::AccessFlags2::SHADER_READ)
            .old_layout(vk::ImageLayout::UNDEFINED)
            .new_layout(vk::ImageLayout::GENERAL)
            .image(self.image)
            .subresource_range(color_range())];
        unsafe { d.device.cmd_pipeline_barrier2(cmd, &vk::DependencyInfo::default().image_memory_barriers(&b)) };
        self.ready = true;
    }

    pub fn destroy(&self, d: &Device) {
        unsafe {
            d.device.destroy_image_view(self.view, None);
            d.device.destroy_image(self.image, None);
            d.device.free_memory(self.memory, None);
        }
    }
}

fn color_range() -> vk::ImageSubresourceRange {
    vk::ImageSubresourceRange {
        aspect_mask: vk::ImageAspectFlags::COLOR,
        base_mip_level: 0,
        level_count: 1,
        base_array_layer: 0,
        layer_count: 1,
    }
}

/// f32 to IEEE half, rounded to nearest even (as Mesa stores GL_FLOAT data
/// into a GL_R16F texture).
pub fn half_rne(x: f32) -> u16 {
    let b = x.to_bits();
    let sign = ((b >> 16) & 0x8000) as u16;
    let exp = ((b >> 23) & 0xff) as i32;
    let man = b & 0x7f_ffff;
    if exp == 255 {
        return sign | 0x7c00 | if man != 0 { 0x200 } else { 0 };
    }
    let e = exp - 112; // the half's biased exponent
    if e >= 31 {
        return sign | 0x7c00;
    }
    let (r, rem, halfway) = if e <= 0 {
        if e < -10 {
            return sign;
        }
        let m = man | 0x80_0000;
        let shift = (14 - e) as u32;
        (m >> shift, m & ((1 << shift) - 1), 1u32 << (shift - 1))
    } else {
        (((e as u32) << 10) | (man >> 13), man & 0x1fff, 0x1000)
    };
    // A carry out of the mantissa steps the exponent (up to infinity): still right.
    let r = if rem > halfway || (rem == halfway && r & 1 == 1) { r + 1 } else { r };
    sign | r as u16
}
