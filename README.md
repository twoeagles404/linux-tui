# Linux TUI

A portable Linux administration toolkit inspired by [ProxMenux](https://github.com/MacRimi/ProxMenux), intended for Linux VMs, LXC guests and bare-metal systems without Proxmox integration.

**Status: research baseline and working read-only foundation. Full retained feature parity is not implemented yet.**

The [feature scope](docs/SCOPE.md) captures retained, adapted and excluded functionality. The [architecture](docs/ARCHITECTURE.md) defines runtime boundaries, adapters, delivery stages and acceptance requirements. The [source inventory](docs/research/upstream-files.md) accounts for every tracked file at a pinned upstream commit; the accompanying JSON contains line-level source evidence.

## Run

Python 3.11+; no pip dependencies required for the foundation. Run from this directory:

```console
python -m linux_tui
python -m linux_tui --discover
python -m linux_tui --catalog
python -m linux_tui --run disks
python -m unittest discover -s tests -v
python tools/smoke_test.py
```

The menu currently offers 14 read-only diagnostics covering system, storage, networking, services and hardware. Missing commands and non-Linux systems are explicitly reported. Linux command output and permissions depend on the environment. GNU-specific options may fail on BusyBox; those failures are returned rather than claiming successful collection. Windows supports catalog/research preview only. No packages are installed, services changed or disks modified.

The smoke test requires Linux, exercises every diagnostic, and opens a pseudo-terminal to verify discovery, action selection and exit in the actual interactive menu. Missing optional hardware commands are reported as unavailable; failed commands and missing core commands fail the run. GitHub Actions runs unit/CLI checks on Windows and Ubuntu with Python 3.11 and 3.14, plus live smoke tests on Ubuntu.

## Reproduce the research

```console
git clone https://github.com/MacRimi/ProxMenux.git .research/ProxMenux
git -C .research/ProxMenux checkout 7215c551d402370408b1c7a70c1833066af046a2
python tools/inventory_upstream.py
```

The ignored research clone is reference material. No upstream scripts are executed by this application. Retained parity is a release acceptance goal tracked in the scope and architecture, not inferred from the number of files inventoried.
