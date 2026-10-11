# Linux TUI

A portable Linux administration toolkit inspired by [ProxMenux](https://github.com/MacRimi/ProxMenux), intended for Linux VMs, LXC guests and bare-metal systems without Proxmox integration.

**Status: research baseline and working read-only foundation. Full retained feature parity is not implemented yet.**

The [feature scope](docs/SCOPE.md) captures retained, adapted and excluded functionality. The [architecture](docs/ARCHITECTURE.md) defines runtime boundaries, adapters, delivery stages and acceptance requirements. The [source inventory](docs/research/upstream-files.md) accounts for every tracked file at a pinned upstream commit; the accompanying JSON contains line-level source evidence.

## Quick setup

Requirements: Linux, Git and Python 3.11 or newer. No sudo, pip packages or background service is required. The setup installs for the current user.

Run this setup command:

```bash
git clone https://github.com/twoeagles404/linux-tui.git && cd linux-tui && python3 tools/install.py && "$HOME/.local/bin/linux-tui"
```

Or run the steps separately:

```bash
git clone https://github.com/twoeagles404/linux-tui.git
cd linux-tui
python3 tools/install.py
"$HOME/.local/bin/linux-tui"
```

Public repositories need no GitHub login for this HTTPS command. If the repository is private, authenticate using your credential helper or `gh auth login` followed by `gh auth setup-git`. An SSH key also works with `git clone git@github.com:twoeagles404/linux-tui.git`. Do not put access tokens into setup commands.

## The linux-tui command

Add the user command directory to your current shell:

```bash
export PATH="$HOME/.local/bin:$PATH"
linux-tui
```

For Bash, add that `export` line to `~/.bashrc`; for Zsh, add it to `~/.zshrc`.

```bash
linux-tui --help
linux-tui --version
linux-tui --discover
linux-tui --catalog
linux-tui --run disks
```

Choose a numbered diagnostic from the menu, `d` for environment discovery, or `q` to quit. Commands work over SSH and inside Linux guests. Missing dependencies and permissions are reported per diagnostic; the installer does not install diagnostic utilities automatically. Run as your normal user first; some logs or hardware data may require additional permissions.

Installed files: `~/.local/share/linux-tui/linux_tui/` and `~/.local/bin/linux-tui`. The launcher uses the Python interpreter used during setup. A custom installation prefix is available with `python3 tools/install.py --prefix /your/path`.

## Update

From your cloned repository:

```bash
git pull --ff-only
python3 tools/install.py
```

## Uninstall

Remove the application files and launcher (the cloned repository can be kept):

```bash
rm -r -- "$HOME/.local/share/linux-tui"
rm -- "$HOME/.local/bin/linux-tui"
```

If you used a custom prefix, use its corresponding `share/linux-tui` directory and `bin/linux-tui` launcher instead.

## Development and tests

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

Live VM results are documented in [TESTING.md](docs/TESTING.md). The current release is a terminal application; a web dashboard and full administration workflows are planned.

## Reproduce the research

```console
git clone https://github.com/MacRimi/ProxMenux.git .research/ProxMenux
git -C .research/ProxMenux checkout 7215c551d402370408b1c7a70c1833066af046a2
python tools/inventory_upstream.py
```

The ignored research clone is reference material. No upstream scripts are executed by this application. Retained parity is a release acceptance goal tracked in the scope and architecture, not inferred from the number of files inventoried.
