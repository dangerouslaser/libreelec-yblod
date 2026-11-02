//! The Vulkan device: the physical device behind a DRM render node, one
//! compute-capable queue, and the extensions/features the engine needs.

use ash::{ext, khr, vk};
use std::ffi::CStr;

#[derive(Debug)]
pub enum Error {
    Vk(vk::Result),
    Load(String),
    NoDevice(String),
    Missing(&'static str),
    Unsupported(String),
}

impl From<vk::Result> for Error {
    fn from(r: vk::Result) -> Self {
        Error::Vk(r)
    }
}

impl std::fmt::Display for Error {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Error::Vk(r) => write!(f, "Vulkan: {r:?}"),
            Error::Load(s) => write!(f, "loader: {s}"),
            Error::NoDevice(s) => write!(f, "no device: {s}"),
            Error::Missing(s) => write!(f, "missing {s}"),
            Error::Unsupported(s) => write!(f, "unsupported: {s}"),
        }
    }
}

pub type Result<T> = std::result::Result<T, Error>;

const DEVICE_EXTENSIONS: &[&CStr] = &[
    khr::external_memory_fd::NAME,
    ext::external_memory_dma_buf::NAME,
    ext::image_drm_format_modifier::NAME,
    khr::external_semaphore_fd::NAME,
    ext::queue_family_foreign::NAME,
    khr::push_descriptor::NAME,
];

pub struct Device {
    pub entry: ash::Entry,
    pub instance: ash::Instance,
    pub physical: vk::PhysicalDevice,
    pub device: ash::Device,
    pub queue: vk::Queue,
    pub queue_family: u32,
    pub memory: vk::PhysicalDeviceMemoryProperties,
    pub memory_fd: khr::external_memory_fd::Device,
    pub semaphore_fd: khr::external_semaphore_fd::Device,
    pub modifier: ext::image_drm_format_modifier::Device,
    pub name: String,
    pub driver: String,
    pub timestamp_period: f32,
    pub calibration: Option<ext::calibrated_timestamps::Device>,
    /// DVVK_SUBGROUP=N: the subgroup (SIMD) width every compute pipeline is
    /// created with, when the device can require it (0: the driver's choice).
    pub subgroup_size: u32,
    /// Validated once at device creation; zero explicitly restores driver choice.
    pub subgroup_overrides: std::collections::BTreeMap<String, u32>,
    /// The engine's environment settings, read once (options.rs).
    pub options: crate::options::EngineOptions,
    /// Compiled pipelines, kept in $XDG_CACHE_HOME/dv-engine-vk between runs.
    pub pipeline_cache: vk::PipelineCache,
    pipeline_cache_path: Option<std::path::PathBuf>,
}

/// (major, minor) of a DRM device node's fd.
pub fn drm_node(fd: i32) -> Result<(i64, i64)> {
    let mut st: libc::stat = unsafe { std::mem::zeroed() };
    if unsafe { libc::fstat(fd, &mut st) } != 0 {
        return Err(Error::NoDevice("fstat on the DRM fd failed".into()));
    }
    let rdev = st.st_rdev;
    Ok((libc::major(rdev) as i64, libc::minor(rdev) as i64))
}

impl Device {
    /// The Vulkan device for this DRM fd (render or primary node).
    pub fn new(drm_fd: i32, options: crate::options::EngineOptions) -> Result<Self> {
        let node = drm_node(drm_fd)?;
        let entry = unsafe { ash::Entry::load() }.map_err(|e| Error::Load(e.to_string()))?;
        let app = vk::ApplicationInfo::default().application_name(c"dv-engine-vk").api_version(vk::API_VERSION_1_3);
        let instance =
            unsafe { entry.create_instance(&vk::InstanceCreateInfo::default().application_info(&app), None) }?;
        match Self::with_instance(entry.clone(), instance.clone(), node, options) {
            Ok(d) => Ok(d),
            Err(e) => {
                unsafe { instance.destroy_instance(None) };
                Err(e)
            }
        }
    }

    fn with_instance(
        entry: ash::Entry,
        instance: ash::Instance,
        node: (i64, i64),
        options: crate::options::EngineOptions,
    ) -> Result<Self> {
        let mut chosen = None;
        for pd in unsafe { instance.enumerate_physical_devices() }? {
            let mut drm = vk::PhysicalDeviceDrmPropertiesEXT::default();
            let mut driver = vk::PhysicalDeviceDriverProperties::default();
            let mut props = vk::PhysicalDeviceProperties2::default().push_next(&mut drm).push_next(&mut driver);
            let exts = unsafe { instance.enumerate_device_extension_properties(pd) }?;
            let has_drm = exts.iter().any(|e| e.extension_name_as_c_str().ok() == Some(ext::physical_device_drm::NAME));
            if !has_drm {
                continue;
            }
            unsafe { instance.get_physical_device_properties2(pd, &mut props) };
            let name = props.properties.device_name_as_c_str().unwrap_or(c"?").to_string_lossy().into_owned();
            let period = props.properties.limits.timestamp_period;
            let _ = props;
            let primary = drm.has_primary != 0 && (drm.primary_major, drm.primary_minor) == node;
            let render = drm.has_render != 0 && (drm.render_major, drm.render_minor) == node;
            if primary || render {
                let drv = driver.driver_info_as_c_str().unwrap_or(c"?").to_string_lossy().into_owned();
                chosen = Some((pd, name, drv, period));
                break;
            }
        }
        let (physical, name, driver, timestamp_period) =
            chosen.ok_or_else(|| Error::NoDevice(format!("no Vulkan device for DRM node {}:{}", node.0, node.1)))?;

        let exts = unsafe { instance.enumerate_device_extension_properties(physical) }?;
        for want in DEVICE_EXTENSIONS {
            if !exts.iter().any(|e| e.extension_name_as_c_str().ok() == Some(*want)) {
                return Err(Error::Unsupported(format!("device extension {}", want.to_string_lossy())));
            }
        }

        let mut f12 = vk::PhysicalDeviceVulkan12Features::default();
        let mut f11 = vk::PhysicalDeviceVulkan11Features::default();
        let mut f13 = vk::PhysicalDeviceVulkan13Features::default();
        let mut f = vk::PhysicalDeviceFeatures2::default().push_next(&mut f11).push_next(&mut f12).push_next(&mut f13);
        unsafe { instance.get_physical_device_features2(physical, &mut f) };
        let have = f.features.shader_int64 != 0
            && f.features.shader_int16 != 0
            && f11.storage_buffer16_bit_access != 0
            && f12.storage_buffer8_bit_access != 0
            && f12.timeline_semaphore != 0
            && f13.synchronization2 != 0
            && f13.maintenance4 != 0;
        if !have {
            return Err(Error::Unsupported(
                "int64/int16, 8/16-bit storage, timeline semaphores, sync2, maintenance4".into(),
            ));
        }

        let families = unsafe { instance.get_physical_device_queue_family_properties(physical) };
        let queue_family = families
            .iter()
            .position(|q| q.queue_flags.contains(vk::QueueFlags::COMPUTE))
            .ok_or(Error::Missing("a compute queue"))? as u32;

        let features = vk::PhysicalDeviceFeatures::default().shader_int64(true).shader_int16(true);
        let mut e11 = vk::PhysicalDeviceVulkan11Features::default().storage_buffer16_bit_access(true);
        let mut e12 = vk::PhysicalDeviceVulkan12Features::default()
            .storage_buffer8_bit_access(true)
            .shader_int8(f12.shader_int8 != 0)
            .timeline_semaphore(true)
            .host_query_reset(f12.host_query_reset != 0);
        // DVVK_SUBGROUP=N (e.g. 32 on Intel, 32/64 on AMD): a required compute
        // subgroup size, if the device supports subgroup size control for it.
        let mut p13 = vk::PhysicalDeviceVulkan13Properties::default();
        let mut props2 = vk::PhysicalDeviceProperties2::default().push_next(&mut p13);
        unsafe { instance.get_physical_device_properties2(physical, &mut props2) };
        let wanted = options.subgroup;
        let subgroup_size = if wanted.is_power_of_two()
            && f13.subgroup_size_control != 0
            && p13.required_subgroup_size_stages.contains(vk::ShaderStageFlags::COMPUTE)
            && (p13.min_subgroup_size..=p13.max_subgroup_size).contains(&wanted)
        {
            wanted
        } else {
            if wanted != 0 {
                eprintln!(
                    "dv-engine-vk: DVVK_SUBGROUP={wanted} not supported (subgroup sizes {}-{}), the driver's choice",
                    p13.min_subgroup_size, p13.max_subgroup_size
                );
            }
            0
        };
        let subgroup_overrides = parse_subgroup_overrides(
            &options.subgroup_overrides,
            |name| crate::gpu::SHADERS.iter().any(|(n, _)| *n == name),
            |size| {
                size == 0
                    || (size.is_power_of_two()
                        && f13.subgroup_size_control != 0
                        && p13.required_subgroup_size_stages.contains(vk::ShaderStageFlags::COMPUTE)
                        && (p13.min_subgroup_size..=p13.max_subgroup_size).contains(&size))
            },
        );
        for (name, size) in &subgroup_overrides {
            eprintln!("dv-engine-vk: subgroup override {name}={size}");
        }
        let subgroup_control = subgroup_size != 0 || subgroup_overrides.values().any(|&v| v != 0);
        let mut e13 = vk::PhysicalDeviceVulkan13Features::default()
            .synchronization2(true)
            // pack uses LocalSizeId specialization (SPIR-V 1.6).
            .maintenance4(true)
            .subgroup_size_control(subgroup_control);
        let priorities = [1.0f32];
        let queues =
            [vk::DeviceQueueCreateInfo::default().queue_family_index(queue_family).queue_priorities(&priorities)];
        let mut ext_names: Vec<*const i8> = DEVICE_EXTENSIONS.iter().map(|e| e.as_ptr()).collect();
        // Optional diagnostics only; never require this extension for playback.
        let calibrate = options.deadline_trace
            && exts.iter().any(|e| e.extension_name_as_c_str().ok() == Some(ext::calibrated_timestamps::NAME))
            && unsafe {
                ext::calibrated_timestamps::Instance::new(&entry, &instance)
                    .get_physical_device_calibrateable_time_domains(physical)
            }
            .map(|v| v.contains(&vk::TimeDomainEXT::CLOCK_MONOTONIC) && v.contains(&vk::TimeDomainEXT::DEVICE))
            .unwrap_or(false);
        if calibrate {
            ext_names.push(ext::calibrated_timestamps::NAME.as_ptr());
        }
        let info = vk::DeviceCreateInfo::default()
            .queue_create_infos(&queues)
            .enabled_extension_names(&ext_names)
            .enabled_features(&features)
            .push_next(&mut e11)
            .push_next(&mut e12)
            .push_next(&mut e13);
        let device = unsafe { instance.create_device(physical, &info, None) }?;
        let queue = unsafe { device.get_device_queue(queue_family, 0) };
        let memory = unsafe { instance.get_physical_device_memory_properties(physical) };
        let pipeline_cache_path = pipeline_cache_path(&unsafe { instance.get_physical_device_properties(physical) });
        let initial = pipeline_cache_path
            .as_ref()
            .and_then(|p| std::fs::read(p).ok())
            .filter(|data| data.len() <= PIPELINE_CACHE_MAX)
            .unwrap_or_default();
        // The driver checks the data's header (vendor, device, cache UUID) and
        // starts empty on a mismatch; a failure with data retries without it.
        let pipeline_cache = match unsafe {
            device.create_pipeline_cache(&vk::PipelineCacheCreateInfo::default().initial_data(&initial), None)
        } {
            Ok(c) => c,
            Err(_) if !initial.is_empty() => {
                match unsafe { device.create_pipeline_cache(&vk::PipelineCacheCreateInfo::default(), None) } {
                    Ok(c) => c,
                    Err(e) => {
                        unsafe { device.destroy_device(None) };
                        return Err(e.into());
                    }
                }
            }
            Err(e) => {
                unsafe { device.destroy_device(None) };
                return Err(e.into());
            }
        };
        Ok(Device {
            calibration: calibrate.then(|| ext::calibrated_timestamps::Device::new(&instance, &device)),
            memory_fd: khr::external_memory_fd::Device::new(&instance, &device),
            semaphore_fd: khr::external_semaphore_fd::Device::new(&instance, &device),
            modifier: ext::image_drm_format_modifier::Device::new(&instance, &device),
            entry,
            instance,
            physical,
            device,
            queue,
            queue_family,
            memory,
            name,
            driver,
            timestamp_period,
            subgroup_size,
            subgroup_overrides,
            options,
            pipeline_cache,
            pipeline_cache_path,
        })
    }

    /// A memory type in `bits` with `flags`.
    pub fn memory_type(&self, bits: u32, flags: vk::MemoryPropertyFlags) -> Option<u32> {
        (0..self.memory.memory_type_count)
            .find(|&i| bits & (1 << i) != 0 && self.memory.memory_types[i as usize].property_flags.contains(flags))
    }
}

const PIPELINE_CACHE_MAX: usize = 64 << 20;

/// $XDG_CACHE_HOME/dv-engine-vk/pipelines-VENDOR-DEVICE-UUID.bin (~/.cache
/// without XDG_CACHE_HOME); None (an in-memory cache) without either.
fn pipeline_cache_path(p: &vk::PhysicalDeviceProperties) -> Option<std::path::PathBuf> {
    let base =
        std::env::var_os("XDG_CACHE_HOME").filter(|v| !v.is_empty()).map(std::path::PathBuf::from).or_else(|| {
            std::env::var_os("HOME").filter(|v| !v.is_empty()).map(|h| std::path::PathBuf::from(h).join(".cache"))
        })?;
    let uuid: String = p.pipeline_cache_uuid.iter().map(|b| format!("{b:02x}")).collect();
    Some(base.join("dv-engine-vk").join(format!("pipelines-{:04x}-{:04x}-{uuid}.bin", p.vendor_id, p.device_id)))
}

impl Device {
    /// Writes the pipeline cache back (best effort: a temporary file renamed
    /// over the old one, so a concurrent reader sees one or the other).
    pub fn save_pipeline_cache(&self) {
        let Some(path) = &self.pipeline_cache_path else { return };
        let Ok(data) = (unsafe { self.device.get_pipeline_cache_data(self.pipeline_cache) }) else { return };
        if data.is_empty()
            || data.len() > PIPELINE_CACHE_MAX
            || std::fs::read(path).map(|old| old == data).unwrap_or(false)
        {
            return;
        }
        let Some(dir) = path.parent() else { return };
        let tmp = dir.join(format!(".pipelines-{}.tmp", std::process::id()));
        let written = std::fs::create_dir_all(dir)
            .and_then(|_| std::fs::write(&tmp, &data))
            .and_then(|_| std::fs::rename(&tmp, path));
        if let Err(e) = written {
            let _ = std::fs::remove_file(&tmp);
            eprintln!("dv-engine-vk: pipeline cache not saved ({}): {e}", path.display());
        }
    }

    /// A void destructor must not turn an idle error into permission to recycle
    /// external inputs. This is fail-stop, not device-loss recovery.
    pub fn require_idle(&self) {
        if let Err(e) = unsafe { self.device.device_wait_idle() } {
            eprintln!("dvvk: idle failed during destruction ({e:?}); terminating without resource cleanup");
            // No atexit handlers or unwinding: both may release GPU inputs.
            // The GPU power level is not a GPU input: put it back first.
            crate::power::restore_now();
            unsafe { libc::_exit(1) };
        }
    }
}

impl Drop for Device {
    fn drop(&mut self) {
        self.require_idle();
        unsafe {
            self.device.destroy_pipeline_cache(self.pipeline_cache, None);
            self.device.destroy_device(None);
            self.instance.destroy_instance(None);
        }
    }
}

/// Invalid entries retain the global policy; duplicate names use the last valid
/// entry. Names are shader stems, so all specialization variants stay together.
fn parse_subgroup_overrides(
    text: &str,
    known: impl Fn(&str) -> bool,
    supported: impl Fn(u32) -> bool,
) -> std::collections::BTreeMap<String, u32> {
    let mut result = std::collections::BTreeMap::new();
    for entry in text.split(',').map(str::trim).filter(|s| !s.is_empty()) {
        let parsed = entry.split_once('=').and_then(|(name, value)| {
            let name = name.trim();
            let size = value.trim().parse::<u32>().ok()?;
            (known(name) && supported(size)).then_some((name.to_owned(), size))
        });
        if let Some((name, size)) = parsed {
            result.insert(name, size);
        } else {
            eprintln!("dv-engine-vk: ignoring invalid/unsupported subgroup override {entry:?}");
        }
    }
    result
}

#[cfg(test)]
mod subgroup_tests {
    use super::parse_subgroup_overrides;
    #[test]
    fn capability_and_name_guards() {
        let p = parse_subgroup_overrides(
            "pack=16,cb1_bounds=0,unknown=16,pack=32,pack=3,bad,pack=-1",
            |n| ["pack", "cb1_bounds"].contains(&n),
            |v| [0, 8, 16].contains(&v),
        );
        assert_eq!(p.len(), 2);
        assert_eq!(p["pack"], 16);
        assert_eq!(p["cb1_bounds"], 0);
        assert!(parse_subgroup_overrides("pack=16", |_| true, |v| v == 0).is_empty());
    }
    #[test]
    fn explicit_driver_and_duplicate_policy() {
        let p = parse_subgroup_overrides(" pack = 16, pack=0, , cb1_bounds=8 ", |_| true, |_| true);
        assert_eq!(p["pack"], 0);
        assert_eq!(p["cb1_bounds"], 8);
        assert!(parse_subgroup_overrides("", |_| true, |_| true).is_empty());
    }
}
