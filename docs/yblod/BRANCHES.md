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
    tools/yblod/build.sh 0.2-test         # then test on hardware and open a pull request

## Taking a single LibreELEC fix early

    git switch -c fix/<name> main
    git cherry-pick -x <commit>           # -x records the upstream commit

## Releasing

    tools/yblod/build.sh <version>
    tools/yblod/release.py <version> target
    git tag yblod-<version>; push; create the GitHub release "yblod-<version>" with the .tar, .img.gz
    and their .sha256 files.
