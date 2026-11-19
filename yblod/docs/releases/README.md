# yblod/docs/releases

What each YBLOD release published: its notes (`RELEASE-<version>`), the
checks made on the image before it was released
(`RELEASE-CHECK-<version>-<date>`) and, from 0.5.0, the data behind the
notes' tables (`data/`). A GitHub release's text is its notes and its
attached validation report is its check, and the notes point here for
their data: these are records, never edited or renamed. A release adds
its two files here.

| Version | Notes | Checks |
|---|---|---|
| 0.2-pre7 | [RELEASE-0.2-pre7.md](RELEASE-0.2-pre7.md) | |
| 0.2 | [RELEASE-0.2.md](RELEASE-0.2.md) | [RELEASE-CHECK-0.2-20261010.txt](RELEASE-CHECK-0.2-20261010.txt) |
| 0.2.1 | [RELEASE-0.2.1.txt](RELEASE-0.2.1.txt) | [RELEASE-CHECK-0.2.1-20261010.txt](RELEASE-CHECK-0.2.1-20261010.txt) |
| 0.2.2 | [RELEASE-0.2.2.txt](RELEASE-0.2.2.txt) | [RELEASE-CHECK-0.2.2-20261011.txt](RELEASE-CHECK-0.2.2-20261011.txt) |
| 0.2.3 | [RELEASE-0.2.3.txt](RELEASE-0.2.3.txt) | [RELEASE-CHECK-0.2.3-20261011.txt](RELEASE-CHECK-0.2.3-20261011.txt) |
| 0.2.4 | [RELEASE-0.2.4.txt](RELEASE-0.2.4.txt) | [RELEASE-CHECK-0.2.4-20261012.txt](RELEASE-CHECK-0.2.4-20261012.txt) |
| 0.2.5 | [RELEASE-0.2.5.txt](RELEASE-0.2.5.txt) | [RELEASE-CHECK-0.2.5-20261012.txt](RELEASE-CHECK-0.2.5-20261012.txt) |
| 0.2.6 | [RELEASE-0.2.6.txt](RELEASE-0.2.6.txt) | [RELEASE-CHECK-0.2.6-20261013.txt](RELEASE-CHECK-0.2.6-20261013.txt) |
| 0.2.7 | [RELEASE-0.2.7.txt](RELEASE-0.2.7.txt) | [RELEASE-CHECK-0.2.7-20261013.txt](RELEASE-CHECK-0.2.7-20261013.txt) |
| 0.2.8 | [RELEASE-0.2.8.txt](RELEASE-0.2.8.txt) | [RELEASE-CHECK-0.2.8-20261015.txt](RELEASE-CHECK-0.2.8-20261015.txt) |
| 0.2.9 | [RELEASE-0.2.9.txt](RELEASE-0.2.9.txt) | [RELEASE-CHECK-0.2.9-20261023.txt](RELEASE-CHECK-0.2.9-20261023.txt) |
| 0.3.0 | [RELEASE-0.3.0.txt](RELEASE-0.3.0.txt) | [RELEASE-CHECK-0.3.0-20261028.txt](RELEASE-CHECK-0.3.0-20261028.txt) |
| 0.3.1 | [RELEASE-0.3.1.txt](RELEASE-0.3.1.txt) | [RELEASE-CHECK-0.3.1-20261030.txt](RELEASE-CHECK-0.3.1-20261030.txt) |
| 0.3.2 | [RELEASE-0.3.2.txt](RELEASE-0.3.2.txt) | [RELEASE-CHECK-0.3.2-20261102.txt](RELEASE-CHECK-0.3.2-20261102.txt) |
| 0.3.3 | [RELEASE-0.3.3.txt](RELEASE-0.3.3.txt) | [RELEASE-CHECK-0.3.3-20261103.txt](RELEASE-CHECK-0.3.3-20261103.txt) |
| 0.3.4 | [RELEASE-0.3.4.txt](RELEASE-0.3.4.txt) | [RELEASE-CHECK-0.3.4-20261108.txt](RELEASE-CHECK-0.3.4-20261108.txt) |
| 0.3.5 | [RELEASE-0.3.5.txt](RELEASE-0.3.5.txt) | [RELEASE-CHECK-0.3.5-20261109.txt](RELEASE-CHECK-0.3.5-20261109.txt) |
| 0.4.0 | [RELEASE-0.4.0.txt](RELEASE-0.4.0.txt) | [RELEASE-CHECK-0.4.0-20261109.txt](RELEASE-CHECK-0.4.0-20261109.txt) |
| 0.4.1 | [RELEASE-0.4.1.txt](RELEASE-0.4.1.txt) | [RELEASE-CHECK-0.4.1-20261110.txt](RELEASE-CHECK-0.4.1-20261110.txt) |
| 0.5.0 | [RELEASE-0.5.0.txt](RELEASE-0.5.0.txt) | [RELEASE-CHECK-0.5.0-20261112.txt](RELEASE-CHECK-0.5.0-20261112.txt) |
| 0.5.1 | [RELEASE-0.5.1.txt](RELEASE-0.5.1.txt) | [RELEASE-CHECK-0.5.1-20261113.txt](RELEASE-CHECK-0.5.1-20261113.txt) |
| 0.6.0 | [RELEASE-0.6.0.txt](RELEASE-0.6.0.txt) | [RELEASE-CHECK-0.6.0-20261118.txt](RELEASE-CHECK-0.6.0-20261118.txt) |

## data/

| File | What |
|---|---|
| [release-0.2-check/](data/release-0.2-check/) | the JSON results behind RELEASE-CHECK-0.2 (N150 and VM: smoke, menu, seek, live) |
| [bench-0.4.1-n150.md](data/bench-0.4.1-n150.md), [.json](data/bench-0.4.1-n150.json) | the playback benchmark of 0.4.1 on the N150, the baseline for 0.5.0 |
| [bench-0.5.0-n150.md](data/bench-0.5.0-n150.md), [.json](data/bench-0.5.0-n150.json) | the same for 0.5.0 |
| [bench-0.4.1-vs-0.5.0-n150.md](data/bench-0.4.1-vs-0.5.0-n150.md) | 0.4.1 against 0.5.0 on the N150: the table in RELEASE-0.5.0.txt |
| [bench-0.5.0-ryzen.md](data/bench-0.5.0-ryzen.md), [.json](data/bench-0.5.0-ryzen.json) | 0.5.0 on AMD (Ryzen 5 3500U, Vega 8) against the N150 |
| [checks-0.5.0-n150.md](data/checks-0.5.0-n150.md) | 0.5.0's functional checks on the N150 |

The harness that made the benchmark and the checks is
[yblod/tools/bench](../../tools/bench/README.md).
