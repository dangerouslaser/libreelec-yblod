# YBLOD repository layout

YBLOD is LibreELEC with a Dolby Vision playback pipeline for Intel GPUs. Almost everything
YBLOD owns lives in two folders, so that resyncing with upstream LibreELEC (and offering
changes to other projects) only has to deal with a short list of glue files.

| Folder | Contents |
|---|---|
| `yblod-engine/` | The Dolby Vision pipeline: the Vulkan engine (`vk/`) and the host C it compiles (`src/`, `tests/`), Kodi's runtime environment (`integration/`), its Kodi, FFmpeg and kernel patches (`patches/<package>/`), tools, docs and licences. |
| `yblod/` | The distribution: patches that are not Dolby Vision (`patches/`), the LG edition (`editions/lg/`), build and release tools (`tools/`), release notes and validation (`docs/releases/`). |
| `releases/` | Update channel files. Installed systems fetch `releases/releases.json` from `main` by URL, so this folder stays at the repository root. |

## Glue outside the two folders

LibreELEC only finds package recipes under `packages/` and only applies patches from a
package's `patches/` folder or `projects/<project>/patches/<package>/`. So:

- **Package recipes** we add stay under `packages/` as thin recipes that read their files
  from `yblod-engine/` or `yblod/` (`packages/graphics/yblod-engine-vk`, shaderc, the LG
  edition packages; the OpenCL engine and its runtime packages were removed in 0.4.0). `PKG_NEED_UNPACK` points at the owning folder,
  so changes there trigger a rebuild.
- **Patches** are stored in `yblod-engine/patches/<package>/` or `yblod/patches/<package>/`
  (the owner folders) and linked into the LibreELEC patch folder, `projects/Generic/patches/
  <package>/` (`packages/mediacenter/LibreELEC-settings/patches/` for that package), by
  relative symlinks. LibreELEC follows them for both patching and change detection, and
  applies them in file-name order exactly as if they were stored there. A file is named
  `<package>-<number>-<subject>.patch` (`kodi-99NN-subject.patch` for Kodi's series, see
  [docs/KODI-PATCHES.md](docs/KODI-PATCHES.md) for its number ranges,
  `linux-99NN-subject.patch`, `ffmpeg-99NN-...`) with a number above LibreELEC's own, so
  it applies after them, and holds a unified diff (`git format-patch` output with a
  description for Kodi's series, `diff -u` or `git diff` elsewhere). After adding,
  renaming or removing a patch, run `yblod/tools/link-patches.sh --fix`. Without
  arguments it only checks, and exits non-zero when an owner patch has no link or the
  wrong one, when a link has no owner patch or points at nothing, when a regular `.patch`
  file sits in a folder that owner folders feed (move it into its owner folder; `--fix`
  never touches a regular file), and when two owner folders hold the same file name.
  `yblod/tools/build.sh` runs the check first and stops on a failure.
- **Upstream files we modify** are kept to a few lines: the Kodi recipe (Kodi does not
  link libplacebo since 0.4.0, and the libplacebo recipe is stock LibreELEC again; the
  engine vendors the part it needs), the `mediacenter` meta package (LG edition),
  `README.md` and `.gitignore`.

`yblod/tools/footprint.sh` lists everything outside the two folders that differs from the
LibreELEC commit of the last resync. Review that list when resyncing.

## Names that stay the same on installed systems

The engine package is `yblod-engine-vk`, but installed paths keep their names so existing
settings keep working: `/usr/lib/kodi/native-dv.env`, the user overrides in
`/storage/.config/native-dv.env` and the `DV_*` settings (0.4.0 dropped the OpenCL
engine's `libdv_source_private.so`, `/usr/share/native-dv` and `/storage/.cache/native-dv`).

## Building

`yblod/tools/build.sh <version>` builds the standard edition in the LibreELEC build
container; `YBLOD_EDITION=lg yblod/tools/build.sh <version>` builds the LG edition. Both
check the patch links first (`yblod/tools/link-patches.sh`) and stop if they are broken.
The image is built for `PROJECT=Generic DEVICE=Generic ARCH=x86_64` (Generic is a link to
OpenGLES's options: GBM, OpenGL ES and Vulkan). The Dolby Vision build of Kodi
(`-DENABLE_DVBRIDGE`, the engine package and the YBLOD skin and iPhone remote) is only
selected for x86_64 Generic with GBM, OpenGL ES and Vulkan; any other Generic device (the
OpenGL, x11 and Wayland ones) or project builds the recipes as LibreELEC does.
`yblod/tools/release.py` adds a built image to `releases/releases.json`. See
`docs/BRANCHES.md` for branches and updates.
