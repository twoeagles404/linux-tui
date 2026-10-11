# Live validation

Validated October 10, 2026 over Tailscale SSH. Project files were staged in `/opt/linux-tui` on two existing servers. No package installation or service/configuration changes were performed.

| Target | OS | Python | Unit and CLI checks | Diagnostics | Interactive menu |
| --- | --- | --- | --- | --- | --- |
| Adminserver | Ubuntu 24.04.5 LTS, KVM VM | 3.12.3 | 10 passed | 13 passed, 1 unavailable | Passed |
| Hetzner | Ubuntu 26.04.1 LTS, KVM VM | 3.14.4 | 10 passed | 13 passed, 1 unavailable | Passed |
| Windows development workstation | Windows | 3.14 | 10 passed | Correctly blocked on non-Linux | Not validated interactively |

The unavailable diagnostic is `sensors`: its executable is not installed on either Linux target. PCI and USB commands completing successfully does not establish access to physical hardware. Adminserver's first journal query hit the 15-second timeout; an isolated retry and the final complete smoke run passed. The timeout handling returned a controlled failure rather than hanging the menu.

The pseudo-terminal smoke check launches the actual menu, chooses discovery, executes the system diagnostic, then exits. Every diagnostic is exercised separately. The smoke script fails on any executed diagnostic failure, on any missing required core diagnostic, or on menu failure. Missing optional hardware commands are explicitly reported.

Only status metadata is recorded here. Raw server logs, processes, network addresses and diagnostic output are not uploaded to the repository.

## Try the deployed menu

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

The application is a terminal tool; there is no web dashboard to visit yet. LXC, non-root execution, Alpine/BusyBox, host mutations and restore workflows are not validated by these VM tests.
