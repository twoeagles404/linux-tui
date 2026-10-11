# Architecture and delivery plan

This document describes the target architecture and acceptance requirements, not a claim that all safeguards/adapters are complete. Current implementation and validation are recorded in [FEATURES.md](FEATURES.md) and [TESTING.md](TESTING.md). Version 0.3 implements portions of stages 2–5, including real administration workflows and an optional authenticated read-only web monitor.

## Runtime

Python 3.11+ core with no mandatory pip dependency. Separate environment discovery, collectors, capability policy, action planning, execution, persistent state and presentation. No Proxmox SDK, API, executable or filesystem dependency. Version 0.2 uses classic full-screen dialog/whiptail category menus with a built-in curses fallback. Command-line JSON diagnostics remain available for scripts.

Discover `/etc/os-release`, architecture, init system, virtualization/container context, cgroup limits, package manager, network/firewall owner, mounted filesystems, available executables, effective UID and actual operation permissions. Root is not a complete capability test. Report ambiguous/unavailable capabilities explicitly.

Adapters: APT (Debian/Ubuntu), DNF (Fedora/RHEL families), APK (Alpine), Pacman (Arch), Zypper (openSUSE); systemd/OpenRC; NetworkManager/networkd/Netplan/ifupdown; firewalld/UFW/nftables; optional libvirt, native LXC, Incus and LXD. Advertise each adapter only after its acceptance tests pass. A distro name alone never proves support.

## Action contract

Each action declares stable ID, category, summary, source parity references, implementation status, required capabilities, supported adapters, inputs, impact, command/configuration preview, validation, cancellation behavior, reboot requirement and rollback limits. Discovery produces a plan; execution applies the reviewed plan and records result. Never use shell `eval` or user-composed shell strings. Use argv, timeouts, bounded output and controlled environment. Unknown action IDs fail closed.

Mutations acquire resource locks, recheck prerequisites, snapshot affected configuration, write atomically, validate, and restore the checkpoint if validation fails. Package upgrades and destructive storage operations explicitly state their rollback limits. Network changes use a timed local recovery mechanism before affecting SSH. Disk operations resolve stable IDs and reject mounted, swap, root, ancestor and dependent devices. Backup extraction validates paths, symlinks, integrity, manifest version and destination constraints before writes.

TUI stays usable without network access or root. The current read-only web monitor can run unprivileged; future web mutations require a separate administrative broker. SSH management uses explicit hosts and host-key verification; local management works without it. Metrics should expose origin, timestamp, collection errors and container scope. Current metrics history uses SQLite; credentials use separate restricted files. Configuration snapshots intentionally contain system secrets and require private storage; notification credentials are never added to delivery history.

## Delivery sequence and acceptance

1. **Research and foundation:** pinned upstream inventory, retained/adapted/excluded scope, runnable local diagnostics/menu, explicit action status, meaningful unit tests.
2. **Guest administration:** tested APT/APK adapters first, services/logs, package update plans, post-install profiles with rollback, utilities, shell customization, backup/restore of app and selected system configuration. Validate Debian/Ubuntu VMs and Alpine/Debian unprivileged LXC, including non-root and read-only failures.
3. **Network/security/storage:** independent network and firewall adapters, Fail2ban/Lynis, shares/mounts, SMART and schedules, safe disk workflows. Validate owner conflicts, SSH recovery, missing physical devices, denied container capabilities and interrupted changes.
4. **Monitoring/web:** history, thresholds, notifications and channel tests, responsive dashboard/PWA, auth/TOTP/token API, reports, integrations and optional AI enrichment. Test privilege separation, secrets redaction, session/token revocation and proxy configuration. AI credentials/setup are a separate opt-in integration task.
5. **Optional host providers:** libvirt VM workflows and native LXC/Incus/LXD workflows, guest inventory/updates, device assignment, image catalogs/import/export and managed apps. Validate on actual supported hosts; never imply guest root can perform host actions.
6. **Parity release:** review every source-evidence record against an implemented action, documented exclusion or nonfunctional asset; run VM/container/distro matrix, fault injection, install/update/uninstall tests, restore drills and internationalization review. Only then claim full retained parity.

## Support matrix target

| Environment | Baseline administration | Physical/host controls |
| --- | --- | --- |
| Linux VM on any hypervisor/cloud | Guest-local features, subject to distro/init/permissions | Only devices exposed to guest; nested virtualization optional |
| Unprivileged LXC/Incus/LXD guest | Guest-local userspace and visible metrics | Kernel, host disks, UID maps and passthrough controlled externally |
| Privileged container | Detected permitted operations only | Never infer permission from privilege label |
| Bare-metal Linux | Guest-local features plus discovered hardware | Optional host provider with actual permissions |
| Non-Linux | Research/catalog preview only | Linux commands disabled |

The Windows development environment verifies parsing, dispatch and mocked Linux discovery. Actual Linux operations require Linux integration validation before support is advertised.
