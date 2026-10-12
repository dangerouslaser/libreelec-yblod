# YBLOD repository layout

YBLOD is LibreELEC with a Dolby Vision playback pipeline for Intel GPUs. Almost everything
YBLOD owns lives in two folders, so that resyncing with upstream LibreELEC (and offering
changes to other projects) only has to deal with a short list of glue files.

| Folder | Contents |
|---|---|
| `yblod-engine/` | The Dolby Vision pipeline: the native engine (`src/`, `tests/`, `integration/`), its Kodi, FFmpeg, libplacebo and kernel patches (`patches/<package>/`), tools, docs and licences. |
| `yblod/` | The distribution: patches that are not Dolby Vision (`patches/`), the LG edition (`editions/lg/`), build and release tools (`tools/`), release notes and validation (`docs/releases/`). |
| `releases/` | Update channel files. Installed systems fetch `releases/releases.json` from `main` by URL, so this folder stays at the repository root. |

## Glue outside the two folders

LibreELEC only finds package recipes under `packages/` and only applies patches from a
package's `patches/` folder or `projects/<project>/patches/<package>/`. So:

- **Package recipes** we add stay under `packages/` as thin recipes that read their files
  from `yblod-engine/` or `yblod/` (`packages/graphics/yblod-engine`, the Intel OpenCL
  runtime packages, the LG edition packages). `PKG_NEED_UNPACK` points at the owning folder,
  so changes there trigger a rebuild.
- **Patches** are stored in `yblod-engine/patches/<package>/` or `yblod/patches/<package>/`
  and linked into the LibreELEC patch folder by relative symlinks. LibreELEC follows them
  for both patching and change detection, and applies them in file-name order exactly as if
  they were stored there. After adding, renaming or removing a patch, run
  `yblod/tools/link-patches.sh --fix`; without arguments it only checks.
- **Upstream files we modify** are kept to a few lines: the Kodi and libplacebo recipes, the
  `mediacenter` meta package (LG edition), `README.md` and `.gitignore`.

`yblod/tools/footprint.sh` lists everything outside the two folders that differs from the
LibreELEC commit of the last resync. Review that list when resyncing.

## Names that stay the same on installed systems

The engine package is `yblod-engine`, but installed paths keep their names so existing
settings keep working: `/usr/lib/kodi/native-dv.env`, the user overrides in
`/storage/.config/native-dv.env`, shaders in `/usr/share/native-dv`, the shader cache in
`/storage/.cache/native-dv`, `DV_*` settings and `libdv_source_private.so`.

## Building

`yblod/tools/build.sh <version>` builds the standard edition in the LibreELEC build
container; `YBLOD_EDITION=lg yblod/tools/build.sh <version>` builds the LG edition.
`yblod/tools/release.py` adds a built image to `releases/releases.json`. See
`docs/BRANCHES.md` for branches and updates.
