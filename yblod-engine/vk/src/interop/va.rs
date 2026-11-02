//! libva: a decoded surface as dmabuf planes (Intel iHD, AMD radeonsi).
//! Hand-written declarations of the few entry points used.

#![allow(non_camel_case_types, non_snake_case, non_upper_case_globals, dead_code)]

use crate::device::{Device, Error, Result};
use crate::interop::dmabuf::{self, ImportedImage, Plane};
use ash::vk;
use std::os::raw::{c_int, c_uint, c_void};

pub type VADisplay = *mut c_void;
pub type VAStatus = c_int;
pub type VASurfaceID = c_uint;
pub const VA_INVALID_SURFACE: VASurfaceID = 0xffff_ffff;

pub const VA_FOURCC_P010: u32 = 0x3031_3050;
pub const VA_FOURCC_NV12: u32 = 0x3231_564e;
pub const VA_RT_FORMAT_YUV420: u32 = 0x1;
pub const VA_RT_FORMAT_YUV420_10: u32 = 0x100;
pub const VA_SURFACE_ATTRIB_MEM_TYPE_DRM_PRIME_2: u32 = 0x4000_0000;
pub const VA_EXPORT_SURFACE_READ_ONLY: u32 = 0x1;
pub const VA_EXPORT_SURFACE_READ_WRITE: u32 = 0x3;
pub const VA_EXPORT_SURFACE_SEPARATE_LAYERS: u32 = 0x4;
pub const VA_EXPORT_SURFACE_COMPOSED_LAYERS: u32 = 0x8;

#[repr(C)]
#[derive(Clone, Copy, Default, Debug)]
pub struct VADRMPRIMEObject {
    pub fd: c_int,
    pub size: u32,
    pub drm_format_modifier: u64,
}

#[repr(C)]
#[derive(Clone, Copy, Default, Debug)]
pub struct VADRMPRIMELayer {
    pub drm_format: u32,
    pub num_planes: u32,
    pub object_index: [u32; 4],
    pub offset: [u32; 4],
    pub pitch: [u32; 4],
}

#[repr(C)]
#[derive(Clone, Copy, Default, Debug)]
pub struct VADRMPRIMESurfaceDescriptor {
    pub fourcc: u32,
    pub width: u32,
    pub height: u32,
    pub num_objects: u32,
    pub objects: [VADRMPRIMEObject; 4],
    pub num_layers: u32,
    pub layers: [VADRMPRIMELayer; 4],
}

#[repr(C)]
#[derive(Clone, Copy)]
pub union VAGenericValueUnion {
    pub i: c_int,
    pub f: f32,
    pub p: *mut c_void,
}

#[repr(C)]
#[derive(Clone, Copy)]
pub struct VAGenericValue {
    pub type_: c_int,
    pub value: VAGenericValueUnion,
}

#[repr(C)]
#[derive(Clone, Copy)]
pub struct VASurfaceAttrib {
    pub type_: c_int,
    pub flags: u32,
    pub value: VAGenericValue,
}
pub const VASurfaceAttribPixelFormat: c_int = 1;
pub const VASurfaceAttribUsageHint: c_int = 8;
pub const VA_SURFACE_ATTRIB_SETTABLE: u32 = 2;
pub const VAGenericValueTypeInteger: c_int = 1;
pub const VA_SURFACE_ATTRIB_USAGE_HINT_DECODER: c_int = 1;

#[repr(C)]
#[derive(Clone, Copy, Default, Debug)]
pub struct VAImageFormat {
    pub fourcc: u32,
    pub byte_order: u32,
    pub bits_per_pixel: u32,
    pub depth: u32,
    pub red_mask: u32,
    pub green_mask: u32,
    pub blue_mask: u32,
    pub alpha_mask: u32,
    pub va_reserved: [u32; 4],
}

#[repr(C)]
#[derive(Clone, Copy, Default, Debug)]
pub struct VAImage {
    pub image_id: u32,
    pub format: VAImageFormat,
    pub buf: u32,
    pub width: u16,
    pub height: u16,
    pub data_size: u32,
    pub num_planes: u32,
    pub pitches: [u32; 3],
    pub offsets: [u32; 3],
    pub num_palette_entries: i32,
    pub entry_bytes: i32,
    pub component_order: [i8; 4],
    pub va_reserved: [u32; 4],
}

extern "C" {
    pub fn vaGetDisplayDRM(fd: c_int) -> VADisplay;
    pub fn vaInitialize(dpy: VADisplay, major: *mut c_int, minor: *mut c_int) -> VAStatus;
    pub fn vaTerminate(dpy: VADisplay) -> VAStatus;
    pub fn vaCreateSurfaces(
        dpy: VADisplay,
        format: c_uint,
        width: c_uint,
        height: c_uint,
        surfaces: *mut VASurfaceID,
        num: c_uint,
        attribs: *mut VASurfaceAttrib,
        num_attribs: c_uint,
    ) -> VAStatus;
    pub fn vaDestroySurfaces(dpy: VADisplay, surfaces: *mut VASurfaceID, num: c_int) -> VAStatus;
    pub fn vaSyncSurface(dpy: VADisplay, surface: VASurfaceID) -> VAStatus;
    pub fn vaDeriveImage(dpy: VADisplay, surface: VASurfaceID, image: *mut VAImage) -> VAStatus;
    pub fn vaDestroyImage(dpy: VADisplay, image: u32) -> VAStatus;
    pub fn vaMapBuffer(dpy: VADisplay, buf: u32, pbuf: *mut *mut c_void) -> VAStatus;
    pub fn vaUnmapBuffer(dpy: VADisplay, buf: u32) -> VAStatus;
    pub fn vaExportSurfaceHandle(
        dpy: VADisplay,
        surface: VASurfaceID,
        mem_type: u32,
        flags: u32,
        descriptor: *mut c_void,
    ) -> VAStatus;
}

/// A decoded 4:2:0 surface's planes as Vulkan images: luma (`R16_UNORM` or
/// `R8_UNORM`) and interleaved chroma (`R16G16_UNORM` / `R8G8_UNORM`), both on
/// the surface's single dmabuf object. Holds that object's fd for implicit sync.
pub struct SurfaceImport {
    pub luma: ImportedImage,
    pub chroma: ImportedImage,
    pub fd: c_int,
    pub modifier: u64,
    pub ten_bit: bool,
    pub key: SurfaceKey,
}

impl SurfaceImport {
    pub fn destroy(&self, d: &Device) {
        self.luma.destroy(d);
        self.chroma.destroy(d);
        unsafe { libc::close(self.fd) };
    }
}

pub fn dmabuf_inode(fd: c_int) -> u64 {
    let mut st: libc::stat = unsafe { std::mem::zeroed() };
    if unsafe { libc::fstat(fd, &mut st) } != 0 {
        return 0;
    }
    st.st_ino
}

// Cache identity includes the complete exported interpretation, not just object 0.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct SurfaceKey {
    dimensions: (u32, u32, u32, u32),
    fourcc: u32,
    objects: Vec<(u64, u32, u64)>,
    layers: Vec<(u32, u32, u32, u32)>,
}

pub struct ExportedSurface {
    desc: VADRMPRIMESurfaceDescriptor,
    pub key: SurfaceKey,
}

impl Drop for ExportedSurface {
    fn drop(&mut self) {
        for o in self.desc.objects.iter().take(self.desc.num_objects as usize) {
            unsafe {
                libc::close(o.fd);
            }
        }
    }
}

fn surface_key(desc: &VADRMPRIMESurfaceDescriptor, width: u32, height: u32) -> Result<SurfaceKey> {
    // Both planes must share the retained implicit-sync object. Supporting
    // separate objects requires waiting on each, not silently retaining only 0.
    if desc.num_objects != 1
        || desc.num_layers != 2
        || width == 0
        || height == 0
        || !width.is_multiple_of(2)
        || !height.is_multiple_of(2)
        || width > desc.width
        || height > desc.height
        || !matches!(desc.fourcc, VA_FOURCC_P010 | VA_FOURCC_NV12)
        || desc.layers[..2].iter().any(|l| l.num_planes != 1 || l.object_index[0] != 0 || l.pitch[0] == 0)
    {
        return Err(Error::Unsupported("surface export layout".into()));
    }
    let inode = dmabuf_inode(desc.objects[0].fd);
    if inode == 0 {
        return Err(Error::Unsupported("surface export fd".into()));
    }
    Ok(SurfaceKey {
        dimensions: (width, height, desc.width, desc.height),
        fourcc: desc.fourcc,
        objects: vec![(inode, desc.objects[0].size, desc.objects[0].drm_format_modifier)],
        layers: desc.layers[..2].iter().map(|l| (l.drm_format, l.object_index[0], l.offset[0], l.pitch[0])).collect(),
    })
}

impl SurfaceKey {
    /// The size the surface was imported for.
    pub fn size(&self) -> (u32, u32) {
        (self.dimensions.0, self.dimensions.1)
    }
}

impl ExportedSurface {
    // (`display` is libva's opaque handle: passed on to libva, never dereferenced here)
    #[allow(clippy::not_unsafe_ptr_arg_deref)]
    pub fn new(display: VADisplay, surface: VASurfaceID, width: u32, height: u32) -> Result<Self> {
        let mut desc = VADRMPRIMESurfaceDescriptor::default();
        let status = unsafe {
            vaExportSurfaceHandle(
                display,
                surface,
                VA_SURFACE_ATTRIB_MEM_TYPE_DRM_PRIME_2,
                VA_EXPORT_SURFACE_READ_ONLY | VA_EXPORT_SURFACE_SEPARATE_LAYERS,
                &mut desc as *mut _ as *mut c_void,
            )
        };
        if status != 0 {
            return Err(Error::Unsupported(format!("vaExportSurfaceHandle: {status}")));
        }
        let key = match surface_key(&desc, width, height) {
            Ok(key) => key,
            Err(e) => {
                for o in desc.objects.iter().take(desc.num_objects as usize) {
                    unsafe {
                        libc::close(o.fd);
                    }
                }
                return Err(e);
            }
        };
        Ok(Self { desc, key })
    }

    pub fn import(&self, d: &Device, width: u32, height: u32) -> Result<SurfaceImport> {
        let desc = &self.desc;
        let ten_bit = desc.fourcc == VA_FOURCC_P010;
        let (lf, cf) = if ten_bit {
            (vk::Format::R16_UNORM, vk::Format::R16G16_UNORM)
        } else {
            (vk::Format::R8_UNORM, vk::Format::R8G8_UNORM)
        };
        let fd = unsafe { libc::fcntl(desc.objects[0].fd, libc::F_DUPFD_CLOEXEC, 0) };
        if fd < 0 {
            return Err(Error::Unsupported("dup of decoded dmabuf failed".into()));
        }
        let plane =
            |i: usize| Plane { fd, offset: desc.layers[i].offset[0] as u64, pitch: desc.layers[i].pitch[0] as u64 };
        let modifier = desc.objects[0].drm_format_modifier;
        let usage = vk::ImageUsageFlags::STORAGE | vk::ImageUsageFlags::SAMPLED;
        let luma = match dmabuf::import_plane(d, plane(0), modifier, lf, width, height, usage) {
            Ok(i) => i,
            Err(e) => {
                unsafe {
                    libc::close(fd);
                }
                return Err(e);
            }
        };
        let chroma = match dmabuf::import_plane(d, plane(1), modifier, cf, width / 2, height / 2, usage) {
            Ok(i) => i,
            Err(e) => {
                luma.destroy(d);
                unsafe {
                    libc::close(fd);
                }
                return Err(e);
            }
        };
        Ok(SurfaceImport { luma, chroma, fd, modifier, ten_bit, key: self.key.clone() })
    }
}

pub fn import_surface(
    d: &Device,
    display: VADisplay,
    surface: VASurfaceID,
    width: u32,
    height: u32,
) -> Result<SurfaceImport> {
    ExportedSurface::new(display, surface, width, height)?.import(d, width, height)
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn same_object_decode_layout_changes_invalidate_identity() {
        let fd = unsafe { libc::eventfd(0, libc::EFD_CLOEXEC) };
        assert!(fd >= 0);
        let mut d = VADRMPRIMESurfaceDescriptor {
            fourcc: VA_FOURCC_P010,
            width: 3840,
            height: 2160,
            num_objects: 1,
            ..Default::default()
        };
        d.objects[0].fd = fd;
        d.objects[0].size = 24883200;
        d.num_layers = 2;
        for l in &mut d.layers[..2] {
            l.num_planes = 1;
            l.pitch[0] = 7680;
        }
        d.layers[1].offset[0] = 16588800;
        let original = surface_key(&d, 3840, 2160).unwrap();
        for field in 0..6 {
            let mut changed = d;
            match field {
                0 => changed.fourcc = VA_FOURCC_NV12,
                1 => changed.layers[1].offset[0] += 64,
                2 => changed.layers[0].pitch[0] += 256,
                3 => changed.layers[1].drm_format = 1,
                4 => changed.objects[0].drm_format_modifier = 1,
                _ => changed.width += 64,
            }
            assert_ne!(original, surface_key(&changed, 3840, 2160).unwrap());
        }
        assert_ne!(original, surface_key(&d, 1920, 1080).unwrap());
        d.layers[1].object_index[0] = 4;
        assert!(surface_key(&d, 3840, 2160).is_err());
        d.num_objects = u32::MAX;
        assert!(surface_key(&d, 3840, 2160).is_err());
        unsafe {
            libc::close(fd);
        }
    }
}
