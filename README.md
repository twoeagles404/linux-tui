# Linux TUI

A portable Linux administration toolkit inspired by [ProxMenux](https://github.com/MacRimi/ProxMenux), intended for Linux VMs, LXC guests and bare-metal systems without Proxmox integration.

**Version 0.2: classic full-screen administration menus. Full retained ProxMenux feature parity is not implemented yet.**

The default interface uses the same blue-screen, bordered menu style as ProxMenux, with category submenus, arrow-key navigation and OK/Cancel buttons. It uses `dialog` or `whiptail` when installed, with a built-in curses fallback.

Main categories: post-install settings, hardware/GPU/TPU, virtual machines and containers, disk/storage, mounts/shares, applications/helper tools, networking, security, utilities, backup/restore, help and settings.

Implemented operations include package refresh/upgrades, installation of selected utilities, QEMU guest agent, Fail2ban and Lynis; system diagnostics; and native Linux inventory/status tools. Package changes require root, a command preview and explicit confirmation. Package managers handle their own final prompts.

Unfinished features are identified in their categories: automated tuning and rollback, VM creation and passthrough, disk formatting/SMART scheduling, share/network/firewall editing, backup/restore orchestration, managed app recipes, web monitoring, notifications and translations. Menu categories do not imply these workflows are already implemented.

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

Use Up/Down to select a category and Enter to open it. Tab switches OK/Cancel; Escape or Cancel goes back; `0` on the main menu exits. Environment discovery is under Help and Info Commands. Output appears in scrollable dialogs rather than a numbered text prompt. To force the built-in blue-screen backend, run `linux-tui --ui curses`.

Commands work over SSH and inside Linux guests. Missing tools and permissions are explained. The installer does not change system packages. Selecting a package operation inside the menu can install/update system packages after confirmation; some packages have installation hooks that start services. Run as your normal user for inspection, or as root for package administration.

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

The CLI retains 14 read-only diagnostics for scripts and automation. Interactive category menus additionally expose reviewed package operations and native Linux tools. Missing commands and non-Linux systems are explicitly reported. GNU-specific options may fail on BusyBox; those failures are returned rather than claiming successful collection. Windows supports catalog/research preview and unit tests only.

The smoke test requires Linux, exercises every diagnostic, and opens pseudo-terminals to verify category navigation, environment discovery, return and exit with both automatic and curses UI backends. It does not apply package changes. Missing optional hardware commands are reported as unavailable; failed commands and missing core commands fail the run. GitHub Actions runs unit/CLI checks on Windows and Ubuntu with Python 3.11 and 3.14, plus live smoke and launcher-install tests on Ubuntu.

Live VM results are documented in [TESTING.md](docs/TESTING.md). The current release is a terminal application; a web dashboard and full administration workflows are planned.

## Reproduce the research

```console
git clone https://github.com/MacRimi/ProxMenux.git .research/ProxMenux
git -C .research/ProxMenux checkout 7215c551d402370408b1c7a70c1833066af046a2
python tools/inventory_upstream.py
```

The ignored research clone is reference material. No upstream scripts are executed by this application. Retained parity is a release acceptance goal tracked in the scope and architecture, not inferred from the number of files inventoried.
