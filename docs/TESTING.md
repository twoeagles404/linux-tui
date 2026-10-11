# Live validation

## Version 0.3 functional workflows

Validated October 10, 2026. Current code is staged at `/opt/linux-tui-ui-test` on both existing servers; their original installations are not replaced by test staging.

| Target | Python | Unit/CLI/HTTP checks | Diagnostics | Native/curses navigation | Sandbox workflows |
| --- | --- | --- | --- | --- | --- |
| Hetzner, Ubuntu KVM VM | 3.14.4 | 42 passed | 13 passed, sensors unavailable | Both passed | All passed |
| Adminserver, Ubuntu KVM VM | 3.12.3 | 42 passed | 13 passed, sensors unavailable | Both passed | All passed |
| Windows workstation | 3.14 | 42 passed | Non-Linux execution blocked | Linux-only | Linux-only |

`tools/smoke_workflows.py` performs actual temporary-file changes and undo with permission preservation, snapshot creation/checksum verification/selective restore, symlink omission and private backup permissions, and starts the real monitor CLI on localhost to check unauthenticated rejection, token-file permissions and authenticated live Linux metrics. All temporary files/listeners are cleaned up. The earlier Python 3.12 test failure was caused by globally mocking `Path.stat`; the test was corrected without bypassing production token permission checks.

Unit tests additionally verify partial-restore rollback, corrupt/traversal archive rejection, retention preserving unrelated ZIP files, saved sysctl runtime undo, invalid network/firewall inputs, disk eligibility filtering, container rejection for kernel GPU driver installation, and notification filtering/dedup/retry with mocked delivery. No external notification is sent.

These checks do not run GPU installation, physical disk formatting, real VM/container creation, production package upgrades, network/firewall changes, server share creation, ZFS changes or daily timer installation. Those implemented adapters still need end-to-end acceptance on suitable disposable hosts. Full parity and LXC/distro coverage remain incomplete; see [FEATURES.md](FEATURES.md).

Reproduce the current tests:

```bash
cd /opt/linux-tui-ui-test
python3 -m unittest discover -s tests -v
python3 tools/smoke_test.py
python3 tools/smoke_workflows.py
python3 -m linux_tui
```

## Version 0.2 menu correction

The original plain numbered prompt has been replaced with ProxMenux-style full-screen category menus. Hetzner (Python 3.14.4) passes 17 unit/CLI tests and pseudo-terminal navigation with both native whiptail and built-in curses. The live check opens Help, views environment information, cancels back to the main menu, then exits. Thirteen diagnostics pass; the missing optional `sensors` command is reported as unavailable.

Package operations are tested for command construction, cancellation and package-name validation. Tests do not upgrade packages or install security tools on the server. APT package execution uses the native package manager after an explicit preview; other package adapters and actual package mutations still need integration validation. Native third-party inventory commands are exposed when installed, but not all have been exercised on these hosts.

## Version 0.1 baseline

Validated October 10, 2026 over Tailscale SSH. Project files were staged in `/opt/linux-tui` on two existing servers. No package installation or service/configuration changes were performed.

| Target | OS | Python | Unit and CLI checks | Diagnostics | Interactive menu |
| --- | --- | --- | --- | --- | --- |
| Adminserver | Ubuntu 24.04.5 LTS, KVM VM | 3.12.3 | 10 passed | 13 passed, 1 unavailable | Passed |
| Hetzner | Ubuntu 26.04.1 LTS, KVM VM | 3.14.4 | 10 passed | 13 passed, 1 unavailable | Passed |
| Windows development workstation | Windows | 3.14 | 10 passed | Correctly blocked on non-Linux | Not validated interactively |

The unavailable diagnostic is `sensors`: its executable is not installed on either Linux target. PCI and USB commands completing successfully does not establish access to physical hardware. Adminserver's first journal query hit the 15-second timeout; an isolated retry and the final complete smoke run passed. The timeout handling returned a controlled failure rather than hanging the menu.

The original pseudo-terminal smoke check launched the plain prompt and exercised discovery and a system diagnostic. Version 0.2 replaces it with full-screen navigation tests. Every diagnostic is exercised separately. The smoke script fails on any executed diagnostic failure, on any missing required core diagnostic, or on menu failure. Missing optional hardware commands are explicitly reported.

Only status metadata is recorded here. Raw server logs, processes, network addresses and diagnostic output are not uploaded to the repository.

## Try the original 0.1 baseline

From a computer on the tailnet:

```console
tailscale ssh root@adminserver
cd /opt/linux-tui
python3 -m linux_tui
```

Use `root@hetzner` for the other target. To reproduce the tests there:

```console
python3 -m unittest discover -s tests -v
python3 tools/smoke_test.py
```

This section describes the original 0.1 staging. Version 0.3 adds an optional web monitor and sandbox restore checks; LXC, non-root Linux execution, Alpine/BusyBox and production host mutations still need acceptance validation.
