"""Capture source evidence without importing or executing upstream code."""
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / '.research' / 'ProxMenux'
OUT = ROOT / 'docs' / 'research'
TEXT = {'.sh', '.py', '.tsx', '.ts', '.json', '.md', '.func', '.yml', '.yaml', '.mjs', '.js'}
MARKERS = re.compile(r'\b(?:pct|qm|pvesh|pveum|pveversion|vzdump|pvecm|pveproxy|pve-firewall)\b|/etc/pve|proxmox-backup-client', re.I)


def main():
    commit = subprocess.check_output(['git', '-C', str(SOURCE), 'rev-parse', 'HEAD'], text=True).strip()
    tracked = subprocess.check_output(['git', '-C', str(SOURCE), 'ls-files'], text=True).splitlines()
    records = []
    for name in tracked:
        path = SOURCE / name
        data = path.read_bytes()
        record = {'path': name, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
        if path.suffix in TEXT or name == 'menu':
            content = data.decode('utf-8', errors='replace')
            evidence = []
            for number, line in enumerate(content.splitlines(), 1):
                kinds = []
                if re.search(r'^\s*(?:async )?def |^[A-Za-z_]\w*\(\)\s*\{|^\s*class ', line):
                    kinds.append('symbol')
                if re.search(r'@\w+(?:\.\w+)*\.route\(', line):
                    kinds.append('route')
                if 'translate ' in line or 'translate(' in line:
                    kinds.append('ui-text')
                if MARKERS.search(line):
                    kinds.append('proxmox-coupling')
                if kinds:
                    evidence.append({'line': number, 'kinds': kinds, 'text': line.strip()})
            record['evidence'] = evidence
            record['coupling_detected'] = any('proxmox-coupling' in e['kinds'] for e in evidence)
        records.append(record)
    OUT.mkdir(parents=True, exist_ok=True)
    payload = {'repository': 'https://github.com/MacRimi/ProxMenux', 'commit': commit,
               'review_date': '2026-10-10', 'files': records,
               'limitations': 'Static evidence, not proof of semantic completeness. Coupling markers are review hints, not automatic exclusion decisions. External scripts are references, not audited implementations.'}
    (OUT / 'upstream-inventory.json').write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding='utf-8')
    lines = ['# Upstream source inventory', '', f'Pinned commit: `{commit}`', '',
             'Every tracked path is recorded, including assets. Symbol, route, UI and coupling evidence is in the accompanying JSON.', '',
             '| Path | Bytes | Proxmox marker detected |', '| --- | ---: | --- |']
    for record in records:
        lines.append(f"| `{record['path']}` | {record['bytes']} | {record.get('coupling_detected', 'asset')} |")
    (OUT / 'upstream-files.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    routes = ['# Upstream API review checklist', '',
              'All statically detected route decorators in tracked Python source. Every route requires a retain/adapt/exclude decision before parity release; listed does not mean implemented.', '']
    route_count = 0
    for record in records:
        evidence = [item for item in record.get('evidence', []) if 'route' in item['kinds']]
        if evidence:
            routes.extend([f"## `{record['path']}`", ''])
            for item in evidence:
                routes.append(f"- [ ] Line {item['line']}: `{item['text']}`")
                route_count += 1
            routes.append('')
    (OUT / 'upstream-api-checklist.md').write_text('\n'.join(routes), encoding='utf-8')
    print(f'Inventoried {len(records)} tracked files at {commit}')
    print(f'Captured {route_count} API route declarations for parity review')


if __name__ == '__main__':
    main()
