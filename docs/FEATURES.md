# Implementation coverage: 0.3.0

This is the implementation ledger against [SCOPE.md](SCOPE.md). A category menu does not count as an implemented workflow. **Full retained ProxMenux parity remains incomplete.**

| Area | Working implementation | Remaining retained scope |
| --- | --- | --- |
| Terminal | dialog/whiptail/curses category menus, text entry including masked secrets, scrollable previews, cancel-first changes | Translations, guided preset batches, progress/cancellation for long-running commands |
| Packages | Refresh/upgrade; curated utilities, guest agent, Fail2ban, Lynis and administration tools with distro package-name mappings; apt/dnf/apk/pacman/zypper command adapters | Full dependency catalog and installation acceptance across all distributions, package uninstall flows |
| Post-install | Journald size, APT IPv4/languages, panic timeout, swappiness, TCP Fast Open, PAM limits; transactional original file/owner/mode and runtime sysctl undo | Logrotate, MOTD/shell, Fastfetch/Figurine/log2ram/RTM, kexec, AMD/NIC/OVS/naming and bootloader profiles |
| System/services | Time zone, NTP, hostname; systemd status/start/stop/restart/enable/disable; OpenRC status/start/stop/restart | OpenRC enable/disable and non-systemd time/hostname adapters |
| Hardware | PCI/USB/GPU/sensor inventory; NVIDIA status; Ubuntu/Debian NVIDIA repository install/update; APT/DNF/pacman Mesa userspace; Coral runtime from an already configured APT repo; container blocks kernel-driver operations | Other distro drivers, Coral repository/PCIe setup, passthrough, permission/device assignment; real GPU/TPU validation |
| Virtualization | libvirt define XML/import qcow2, native LXC download-template create, Incus/LXD container image launch; list/start/shutdown/restart/delete | ISO installation, Windows/NAS templates, image catalogs, VM configuration, OVA/OVF import/export, migrations, device assignment, privilege conversion |
| Storage | Disks/filesystems/mounts; SMART attributes and short/long/abort tests; ext4/XFS whole-disk format restricted to unused unsigned unpartitioned disks | Partition editor, SMART schedules, image import/assignment, physical hardware acceptance tests |
| ZFS | Status/snapshot listing/create snapshot, pool scrub and TRIM | ARC configuration, compression, snapshot/TRIM schedules and retention |
| Mounts/shares | Persistent local and NFS client mounts; mount/unmount; NFS exports restricted to a client network; authenticated SMB exports for existing Samba users; configuration undo | SMB client credentials/mounts, iSCSI, bind mounts through host providers, share deletion/editor, service installation/user provisioning |
| Network | Addresses/routes/sockets/DNS/ping/trace/interface byte counters; temporary NetworkManager IPv4 edits under 120-second native checkpoint rollback | Persistent configuration, networkd/Netplan/ifupdown/OpenRC adapters, bridges/topology, latency reports, repair flows |
| Security | Fail2ban installation/status/ban/unban and SSH jail/trusted network; Lynis audit; UFW/firewalld port allow/remove and rules/status | Firewall enable/disable and general rule CRUD, nftables write adapter, wider jail management/uninstall and audit report lifecycle |
| Applications | Docker/Podman list/logs/inspect/start/stop/restart/remove/pull; Compose validate/deploy/recreate/pull/down/logs | Reviewed application recipe catalog, version discovery, engine updates, unmanaged container recreation |
| Local backups | /etc regular-file snapshots, manifest and SHA-256 checks, selective restore, original-file undo; failed multi-file restore rollback; daily systemd timer and newest-seven retention | Symlink/special-file/empty-directory snapshots, ACL/xattr preservation, broader collectors, cron adapter, configurable scheduling/destination/remapping and deferred boot recovery |
| Borg | Borg 1.x local encrypted repokey init, directory backup, list, verify-data, extraction into empty staging directory | Remote repositories, key export/recovery wizard, encrypted scheduled jobs/retention, direct system recovery planning |
| Monitoring | Linux CPU/load/uptime, host memory, current cgroup v2 memory/quota/usage, root filesystem, network rates; SQLite history bounded to 10,000 samples | cgroup v1 and effective ancestor/cpuset limits, all filesystem/device health, detailed process/event/temperature history and report export |
| Web | Authenticated responsive read-only dashboard, CPU chart, dark/light toggle, metrics/history JSON, Basic/Bearer token authentication, private generated token | Password accounts, TOTP/recovery/sessions, PWA, configurable links/tabs, onboarding, admin broker, web terminal, trusted reverse-proxy/iframe settings |
| Notifications | Gotify/Discord/Telegram/Pushover/SMTP TLS/Apprise (private existing config); masked credential input and private files; explicit delivery test; severity filtering; per-channel dedup/retry; bounded delivery history; CPU/disk/cgroup memory thresholds with five-minute grace and three consecutive samples | Configurable thresholds/templates, richer events and recovery alerts, AI providers/enrichment |
| Integrations/support | Generic authenticated metrics endpoint; installer/update commands; source inventory and coverage ledger | Homepage/HA setup, Tailscale installation, UUP Dump, debug bundles, emergency repair, atomic release switching/uninstall wizard |

## Validation boundaries

Unit tests exercise command validation/cancellation, config failure recovery, runtime sysctl undo, backup integrity/path validation/partial restore rollback/retention, nested cgroup collection, authenticated HTTP access, and mocked notification routing/dedup/retry. These are stronger than checking that menu labels exist, but are **not end-to-end acceptance of every adapter**.

Linux VM smoke tests exercise diagnostics and real whiptail/curses navigation. Sandbox integration tests exercise actual file changes/undo, backups/restore and the running authenticated HTTP monitor. No physical disk is formatted, production network/firewall/share configuration is changed, package upgrades are run, or external notifications are sent during these checks.

Docker lifecycle acceptance has also passed on a disposable network-isolated container on Hetzner; the container and temporary image were removed. Other daemon-backed adapters still need their own acceptance environments. Linux configuration writes/undo acquire per-file locks to reject concurrent Linux TUI changes.

Operations depend on tools, permissions and host capabilities. Incus/LXD need their local daemon; libvirt needs a capable host/default network and virt-install for disk imports; native LXC needs download templates; Compose needs an engine/provider; shares need an installed/running server and appropriate directory permissions. Formatting cannot undo erased data. Package upgrades, service actions, container operations and ZFS actions are native operations without general automatic rollback.

Configuration undo records are stored under `/var/lib/linux-tui/changes`. Snapshots contain secrets: backups and original-file copies are root-only. Local snapshots omit symlinks/special files and are not full-system images. Borg supports a richer directory backup but currently restores only into an empty staging directory.

Web monitoring defaults to `127.0.0.1:8008`. For remote browsing, use an SSH tunnel or an HTTPS reverse proxy; Basic/Bearer credentials need encrypted transport. There are no web mutation endpoints. Notification credentials remain local; tests mock delivery and do not contact providers.
