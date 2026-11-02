//! The overlay's sources in mpv: subtitle / OSD bitmaps (an atlas the CPU
//! fills, composited on the GPU) and the shell's OSD layer (KWin's forwarded
//! dmabuf, imported). The compose pass turns them into the RGBA overlay the
//! tile and colour passes prepare for the pack.

use crate::device::{Device, Error, Result};
use crate::gpu::HostBuffer;
use crate::interop::{dmabuf, va};
use ash::vk;
use std::collections::HashMap;

pub const TILE: u32 = 64;
const MAX_PARTS: usize = 4096;
const PARTS_BYTES: u64 = (MAX_PARTS * 48) as u64; // at 0
const LISTS_OFFSET: u64 = 256 * 1024;
const LISTS_BYTES: u64 = 4 * 1024 * 1024;
const BITMAPS_OFFSET: u64 = LISTS_OFFSET + LISTS_BYTES;
const ATLAS_BYTES: u64 = 24 * 1024 * 1024;

/// One subtitle part (include/dv_engine_vk.h dvvk_sub_part).
#[repr(C)]
#[derive(Clone, Copy)]
pub struct SubPart {
    pub x: i32,
    pub y: i32,
    pub w: u32,
    pub h: u32,
    pub dw: u32,
    pub dh: u32,
    pub stride: u32,
    pub format: u32, // 1 libass A8 + colour, 2 BGRA premultiplied
    pub color: u32,
    pub data: *const u8,
}

/// A dmabuf (include/dv_engine_vk.h dvvk_dmabuf).
#[repr(C)]
#[derive(Clone, Copy)]
pub struct Dmabuf {
    pub width: u32,
    pub height: u32,
    pub format: u32,
    pub modifier: u64,
    pub num_planes: u32,
    pub fd: [i32; 4],
    pub offset: [u32; 4],
    pub stride: [u32; 4],
}

#[derive(Clone, Debug, PartialEq, Eq, Hash)]
struct ShellKey {
    inode: u64,
    width: u32,
    height: u32,
    format: u32,
    modifier: u64,
    planes: Vec<(u32, u32)>,
}

impl ShellKey {
    fn new(b: &Dmabuf) -> Result<Self> {
        if !(1..=4).contains(&b.num_planes) || b.width == 0 || b.height == 0 {
            return Err(Error::Unsupported("overlay dimensions/plane count".into()));
        }
        let inode = va::dmabuf_inode(b.fd[0]);
        if inode == 0 || (0..b.num_planes as usize).any(|i| va::dmabuf_inode(b.fd[i]) != inode || b.stride[i] == 0) {
            return Err(Error::Unsupported("overlay plane fd/stride".into()));
        }
        Ok(Self {
            inode,
            width: b.width,
            height: b.height,
            format: b.format,
            modifier: b.modifier,
            planes: (0..b.num_planes as usize).map(|i| (b.offset[i], b.stride[i])).collect(),
        })
    }
}

pub struct Shell {
    pub image: dmabuf::ImportedImage,
    pub fd: i32, // a dup of plane 0's fd: its implicit fence
    pub scaled: bool,
    // half float, linear light, 1.0 = the overlay's white (AB4H/XB4H: a compositor's
    // desktop with HDR content in it); else 8-bit premultiplied sRGB
    pub linear: bool,
}

pub const SLOTS: usize = 6; // > frames in flight: a change never waits for the GPU

pub struct Sources {
    pub atlas: Vec<HostBuffer>,
    atlas_ticket: [u64; SLOTS],
    pub subs_slot: usize,
    pub subs_parts: u32,
    pub tiles_x: u32,
    shells: HashMap<ShellKey, Shell>,
    shell: Option<ShellKey>,
    pub shell_id: u64,               // the caller's id for it
    pub consumed: HashMap<u64, u64>, // caller id -> ticket of the frame that read it
    pub dirty: bool,
    pub subs_bbox: Option<[u32; 4]>,  // x0, y0, x1, y1 of the current parts
    pub dirty_rect: Option<[u32; 4]>, // what the next compose must redo; None = all
}

fn union(a: Option<[u32; 4]>, b: Option<[u32; 4]>) -> Option<[u32; 4]> {
    match (a, b) {
        (Some(a), Some(b)) => Some([a[0].min(b[0]), a[1].min(b[1]), a[2].max(b[2]), a[3].max(b[3])]),
        (a, None) => a,
        (None, b) => b,
    }
}

impl Sources {
    pub fn new(d: &Device) -> Result<Self> {
        let mut construction = crate::construction::Construction::new(d);
        let mut atlas = Vec::new();
        for slot in 0..SLOTS {
            // Slot zero also supplies valid descriptor ranges before any subtitles.
            let bytes = if slot != 0 { 16 } else { ATLAS_BYTES };
            atlas.push(construction.keep(HostBuffer::new(d, bytes, vk::BufferUsageFlags::STORAGE_BUFFER)?));
        }
        construction.commit();
        Ok(Sources {
            atlas,
            atlas_ticket: [0; SLOTS],
            subs_slot: 0,
            subs_parts: 0,
            tiles_x: 0,
            shells: HashMap::new(),
            shell: None,
            shell_id: 0,
            consumed: HashMap::new(),
            dirty: false,
            subs_bbox: None,
            dirty_rect: Some([0, 0, 0, 0]),
        })
    }

    pub fn has_content(&self) -> bool {
        self.subs_parts > 0 || self.shell.is_some()
    }

    pub fn shell(&self) -> Option<&Shell> {
        self.shell.as_ref().and_then(|k| self.shells.get(k))
    }

    /// The parts into the free atlas slot (`wait` blocks until a ticket is
    /// done: only when this ring slot is still being read).
    /// What must be composited again: the old and new parts' area when only
    /// the subtitles changed (whole canvas after a shell change).
    fn mark(&mut self, rect: Option<[u32; 4]>, all: bool) {
        if all || (self.dirty && self.dirty_rect.is_none()) {
            self.dirty_rect = None;
        } else if self.dirty {
            self.dirty_rect = union(self.dirty_rect, rect);
        } else {
            self.dirty_rect = Some(rect.unwrap_or([0, 0, 0, 0]));
        }
        self.dirty = true;
    }

    pub fn set_subtitles(
        &mut self,
        d: &Device,
        parts: &[SubPart],
        canvas: (u32, u32),
        wait: impl Fn(u64) -> Result<()>,
    ) -> Result<()> {
        let mut bbox: Option<[u32; 4]> = None;
        for p in parts {
            let x0 = p.x.clamp(0, canvas.0 as i32) as u32;
            let y0 = p.y.clamp(0, canvas.1 as i32) as u32;
            let x1 = (p.x + p.dw as i32).clamp(0, canvas.0 as i32) as u32;
            let y1 = (p.y + p.dh as i32).clamp(0, canvas.1 as i32) as u32;
            if x1 > x0 && y1 > y0 {
                bbox = union(bbox, Some([x0, y0, x1, y1]));
            }
        }
        let old = self.subs_bbox;
        if parts.is_empty() {
            self.subs_bbox = bbox;
            self.mark(union(old, bbox), false);
            self.subs_parts = 0;
            return Ok(());
        }
        if parts.len() > MAX_PARTS {
            return Err(Error::Unsupported("too many subtitle parts".into()));
        }
        for p in parts {
            let bpp = if p.format == 1 { 1 } else { 4 };
            if p.w > 0 && p.h > 0 && (p.data.is_null() || (p.stride as u64) < p.w as u64 * bpp) {
                return Err(Error::Unsupported("subtitle part without a bitmap".into()));
            }
        }
        let slot = (self.subs_slot + 1) % SLOTS;
        wait(self.atlas_ticket[slot])?;
        if self.atlas[slot].bytes().len() < ATLAS_BYTES as usize {
            let full = HostBuffer::new(d, ATLAS_BYTES, vk::BufferUsageFlags::STORAGE_BUFFER)?;
            let old = std::mem::replace(&mut self.atlas[slot], full);
            old.destroy(d);
        }
        let tiles_x = canvas.0.div_ceil(TILE);
        let tiles_y = canvas.1.div_ceil(TILE);
        let ntiles = (tiles_x * tiles_y) as usize;
        let buf = self.atlas[slot].bytes_mut();
        // bitmaps, packed rows
        let mut at = BITMAPS_OFFSET as usize;
        let mut table = Vec::with_capacity(parts.len() * 12);
        let mut per_tile: Vec<Vec<u32>> = vec![Vec::new(); ntiles];
        for (n, p) in parts.iter().enumerate() {
            let bpp = if p.format == 1 { 1 } else { 4 };
            let row = (p.w * bpp) as usize;
            let stride = row.next_multiple_of(4);
            if at + stride * p.h as usize > buf.len() {
                return Err(Error::Unsupported("subtitle atlas full".into()));
            }
            for y in 0..p.h as usize {
                let src = unsafe { std::slice::from_raw_parts(p.data.add(y * p.stride as usize), row) };
                buf[at + y * stride..at + y * stride + row].copy_from_slice(src);
            }
            // offsets relative to the bitmaps' range (the shader's binding)
            let rel = (at - BITMAPS_OFFSET as usize) as u32;
            table.extend_from_slice(&[
                p.x as u32,
                p.y as u32,
                p.w,
                p.h,
                p.dw,
                p.dh,
                stride as u32,
                rel,
                p.format,
                p.color,
                0,
                0,
            ]);
            at += stride * p.h as usize;
            // the tiles its destination rectangle touches
            let x0 = p.x.max(0) as u32 / TILE;
            let y0 = p.y.max(0) as u32 / TILE;
            let x1 = ((p.x + p.dw as i32).min(canvas.0 as i32) - 1).max(0) as u32 / TILE;
            let y1 = ((p.y + p.dh as i32).min(canvas.1 as i32) - 1).max(0) as u32 / TILE;
            if p.x + (p.dw as i32) <= 0 || p.y + (p.dh as i32) <= 0 || p.x >= canvas.0 as i32 || p.y >= canvas.1 as i32
            {
                continue;
            }
            for ty in y0..=y1.min(tiles_y - 1) {
                for tx in x0..=x1.min(tiles_x - 1) {
                    per_tile[(ty * tiles_x + tx) as usize].push(n as u32);
                }
            }
        }
        let table_bytes = unsafe { std::slice::from_raw_parts(table.as_ptr() as *const u8, table.len() * 4) };
        buf[..table_bytes.len()].copy_from_slice(table_bytes);
        let mut lists: Vec<u32> = Vec::with_capacity(ntiles + 1 + parts.len());
        let mut offset = (ntiles + 1) as u32;
        for t in &per_tile {
            lists.push(offset);
            offset += t.len() as u32;
        }
        lists.push(offset);
        for t in &per_tile {
            lists.extend_from_slice(t);
        }
        if (lists.len() * 4) as u64 > LISTS_BYTES {
            return Err(Error::Unsupported("subtitle tile lists full".into()));
        }
        let lb = unsafe { std::slice::from_raw_parts(lists.as_ptr() as *const u8, lists.len() * 4) };
        buf[LISTS_OFFSET as usize..LISTS_OFFSET as usize + lb.len()].copy_from_slice(lb);
        self.subs_bbox = bbox;
        self.mark(union(old, bbox), false);
        self.subs_slot = slot;
        self.subs_parts = parts.len() as u32;
        self.tiles_x = tiles_x;
        Ok(())
    }

    /// The compose pass reading slot `subs_slot` was submitted as `ticket`.
    pub fn used(&mut self, ticket: u64) {
        self.atlas_ticket[self.subs_slot] = ticket;
        if self.shell.is_some() {
            record_consumed(&mut self.consumed, self.shell_id, ticket);
        }
    }

    pub fn ranges() -> [(u64, u64); 3] {
        [(BITMAPS_OFFSET, ATLAS_BYTES - BITMAPS_OFFSET), (0, PARTS_BYTES), (LISTS_OFFSET, LISTS_BYTES)]
    }

    /// The shell's OSD layer: a new buffer (imported once per allocation),
    /// or none.
    pub fn set_shell(
        &mut self,
        d: &Device,
        buf: Option<&Dmabuf>,
        id: u64,
        idle: impl Fn() -> Result<()>,
    ) -> Result<()> {
        let Some(b) = buf else {
            self.mark(None, true);
            self.shell = None;
            return Ok(());
        };
        let key = ShellKey::new(b)?;
        if !self.shells.contains_key(&key) {
            let (format, alpha_one) = match b.format {
                0x3432_5241 => (vk::Format::B8G8R8A8_UNORM, false),      // AR24
                0x3432_5258 => (vk::Format::B8G8R8A8_UNORM, true),       // XR24
                0x3432_4241 => (vk::Format::R8G8B8A8_UNORM, false),      // AB24
                0x3432_4258 => (vk::Format::R8G8B8A8_UNORM, true),       // XB24
                0x4834_4241 => (vk::Format::R16G16B16A16_SFLOAT, false), // AB4H
                0x4834_4258 => (vk::Format::R16G16B16A16_SFLOAT, true),  // XB4H
                f => return Err(Error::Unsupported(format!("overlay format {f:#010x}"))),
            };
            let planes: Vec<(u64, u64)> = key.planes.iter().map(|&(o, s)| (o as u64, s as u64)).collect();
            let fd = if crate::fault::hit("overlay-dup") {
                -1
            } else {
                unsafe { libc::fcntl(b.fd[0], libc::F_DUPFD_CLOEXEC, 0) }
            };
            if fd < 0 {
                return Err(Error::Unsupported("dup of overlay dmabuf failed".into()));
            }
            let image = match dmabuf::import_image(d, fd, &planes, b.modifier, format, b.width, b.height, alpha_one) {
                Ok(image) => image,
                Err(e) => {
                    unsafe {
                        libc::close(fd);
                    }
                    return Err(e);
                }
            };
            if self.shells.len() >= 8 {
                // Commit only after both import and retirement wait succeed.
                if let Err(e) = idle() {
                    image.destroy(d);
                    unsafe {
                        libc::close(fd);
                    }
                    return Err(e);
                }
                for (_, s) in self.shells.drain() {
                    s.image.destroy(d);
                    unsafe {
                        libc::close(s.fd);
                    }
                }
            }
            let linear = matches!(b.format, 0x4834_4241 | 0x4834_4258);
            self.shells.insert(key.clone(), Shell { image, fd, scaled: b.width != 3840 || b.height != 2160, linear });
        }
        self.mark(None, true);
        self.shell = Some(key);
        self.shell_id = id;
        Ok(())
    }

    pub fn destroy(&mut self, d: &Device) {
        for a in &self.atlas {
            a.destroy(d);
        }
        for (_, s) in self.shells.drain() {
            s.image.destroy(d);
            unsafe { libc::close(s.fd) };
        }
    }
}

// Caller IDs name buffers; they have no ordering contract. Engine tickets are
// monotonic, and ring back-pressure completes tickets this old before pruning.
fn record_consumed(consumed: &mut HashMap<u64, u64>, id: u64, ticket: u64) {
    consumed.insert(id, ticket);
    if consumed.len() > 1024 {
        let recent = ticket.saturating_sub(1024);
        consumed.retain(|_, used| *used > recent);
    }
}

#[cfg(test)]
mod consumed_tests {
    use super::*;
    #[test]
    fn decreasing_ids_do_not_grow_the_consumer_history() {
        let mut consumed = HashMap::new();
        for ticket in 1..=4096 {
            record_consumed(&mut consumed, u64::MAX - ticket, ticket);
            assert!(consumed.len() <= 1024);
        }
        assert_eq!(consumed.get(&(u64::MAX - 4096)), Some(&4096));
        assert!(!consumed.contains_key(&(u64::MAX - 1)));
    }
    #[test]
    fn reused_and_unordered_ids_keep_their_latest_reader() {
        let mut consumed = HashMap::new();
        for ticket in 1u64..=2048 {
            record_consumed(&mut consumed, ticket.wrapping_mul(0x9e3779b97f4a7c15), ticket);
        }
        record_consumed(&mut consumed, 0x9e3779b97f4a7c15, 2049);
        record_consumed(&mut consumed, 0x9e3779b97f4a7c15, 2050);
        assert_eq!(consumed.get(&0x9e3779b97f4a7c15), Some(&2050));
        assert!(consumed.values().all(|&ticket| ticket > 1025));
        assert!(consumed.len() <= 1024);
    }
}

#[cfg(test)]
mod import_tests {
    use super::*;
    #[test]
    fn same_inode_layout_changes_are_distinct_and_invalid_planes_rejected() {
        let fd = unsafe { libc::eventfd(0, libc::EFD_CLOEXEC) };
        assert!(fd >= 0);
        let b = Dmabuf {
            width: 3840,
            height: 2160,
            format: 0x3432_5241,
            modifier: 0,
            num_planes: 1,
            fd: [fd; 4],
            offset: [0; 4],
            stride: [15360; 4],
        };
        let original = ShellKey::new(&b).unwrap();
        let duplicate = unsafe { libc::dup(fd) };
        let mut same = b;
        same.fd[0] = duplicate;
        assert_eq!(original, ShellKey::new(&same).unwrap());
        for field in 0..7 {
            let mut changed = b;
            match field {
                0 => changed.width /= 2,
                1 => changed.height /= 2,
                2 => changed.format = 0x3432_4241,
                3 => changed.modifier = 1,
                4 => changed.num_planes = 2,
                5 => changed.offset[0] = 64,
                _ => changed.stride[0] /= 2,
            }
            assert_ne!(original, ShellKey::new(&changed).unwrap());
        }
        for count in [0, 5, u32::MAX] {
            let mut invalid = b;
            invalid.num_planes = count;
            assert!(ShellKey::new(&invalid).is_err());
        }
        let mut invalid = b;
        invalid.fd[0] = -1;
        assert!(ShellKey::new(&invalid).is_err());
        unsafe {
            libc::close(fd);
            libc::close(duplicate);
        }
    }
}
