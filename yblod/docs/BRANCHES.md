# Branches and updates

| Branch | Contents | Rule |
|---|---|---|
| `master` | Exact mirror of LibreELEC master | Never commit here. Refresh with GitHub "Sync fork". |
| `main` (default) | yblod: a pinned LibreELEC commit plus our commits | Changes arrive by pull request. Releases are tagged here. |
| `feat/*`, `fix/*` | Features and fixes | Pull request into `main`. |
| `update/le-YYYYMMDD` | Moving to a newer LibreELEC master | Merge the LibreELEC commit, build, test, pull request into `main`. |

Tags: `yblod-<version>` (for example `yblod-0.1`). Each tag has a GitHub release with the image files,
and `releases/releases.json` lists it for the LibreELEC updater.

## Moving to a newer LibreELEC

    git fetch upstream
    git switch -c update/le-20261101 main
    git merge <LibreELEC commit>          # merge, don't rebase: tags and clones stay valid
    yblod/tools/build.sh 0.2-test         # then test on hardware and open a pull request

## Taking a single LibreELEC fix early

    git switch -c fix/<name> main
    git cherry-pick -x <commit>           # -x records the upstream commit

## Releasing

    yblod/tools/build.sh <version>
    yblod/tools/release.py <version> target
    git tag yblod-<version>; push; create the GitHub release "yblod-<version>" with the .tar, .img.gz
    and their .sha256 files.

## Resyncing with LibreELEC

`yblod/tools/footprint.sh` lists everything outside `yblod-engine/` and `yblod/` that differs
from the LibreELEC commit of the last resync. Those are the only files a merge can conflict
on. After merging, run `yblod/tools/link-patches.sh` (patch symlinks) and pass the new
LibreELEC commit to `footprint.sh` to check the list is still short.

## Contributing to CroqueMr's libreelec-x86-DV

All YBLOD work lives in this repository. `dangerouslaser/intel-dv-libreelec` is kept as a
clean fork of [CroqueMr/libreelec-x86-DV](https://github.com/CroqueMr/libreelec-x86-DV):
its `main` matches CroqueMr's `main` (refresh with GitHub "Sync fork"), and nothing else is
committed there. To offer a change upstream:

    git clone https://github.com/dangerouslaser/intel-dv-libreelec.git
    git switch -c <feature> origin/main     # CroqueMr's tree, with his CB1 engine
    # port the change (not the YBLOD engine) and open a pull request to CroqueMr/libreelec-x86-DV

The fork's history before 2026-10-12 is kept as tags `intel-dv-libreelec/*` here (its last
`main` is `intel-dv-libreelec/archive/2026-10-12/main-before-croque-reset`), and as tag
`archive/2026-10-12/main-before-croque-reset` in the fork.

Finished experiments are kept as `archive/*` tags rather than branches, so only `main` and
active work appear as branches.
