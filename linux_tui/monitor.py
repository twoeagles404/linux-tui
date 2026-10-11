"""Linux resource collector and optional authenticated, read-only web monitor."""
import base64
from contextlib import closing
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import secrets
import shutil
import sqlite3
import threading
import time

DEFAULT_STATE = Path.home() / '.local/state/linux-tui'


def cgroup_directory(proc=Path('/proc'), sysfs=Path('/sys/fs/cgroup')):
    """Locate this process's unified cgroup, respecting a namespaced mount root."""
    try:
        relative = next(line.split(':', 2)[2] for line in (proc / 'self/cgroup').read_text().splitlines() if line.startswith('0::'))
        for line in (proc / 'self/mountinfo').read_text().splitlines():
            before, after = line.split(' - ', 1)
            if after.split()[0] != 'cgroup2':
                continue
            fields = before.split()
            mount_root, mount_path = fields[3], Path(fields[4])
            if mount_path == Path('/sys/fs/cgroup'):
                if relative == mount_root:
                    return sysfs
                prefix = mount_root.rstrip('/') + '/'
                if relative.startswith(prefix):
                    return sysfs / relative[len(prefix):]
        # In a cgroup namespace the visible path is normally '/', not the host path.
        if relative == '/':
            return sysfs
    except (OSError, StopIteration, ValueError, IndexError):
        pass
    return None


class Collector:
    def __init__(self, proc=Path('/proc'), sysfs=Path('/sys/fs/cgroup')):
        self.proc, self.sysfs = Path(proc), Path(sysfs)
        self.previous = None

    def sample(self):
        now = time.time()
        values = [int(value) for value in (self.proc / 'stat').read_text().splitlines()[0].split()[1:9]]
        total, idle = sum(values), values[3] + values[4]
        memory = {}
        for line in (self.proc / 'meminfo').read_text().splitlines():
            key, value = line.split(':', 1)
            memory[key] = int(value.split()[0]) * 1024
        network = {}
        for line in (self.proc / 'net/dev').read_text().splitlines()[2:]:
            interface, raw = line.split(':', 1)
            counters = raw.split()
            network[interface.strip()] = {'rx_bytes': int(counters[0]), 'tx_bytes': int(counters[8])}
        result = {'time': now, 'cpu_percent': None, 'load': list(os.getloadavg()),
                  'uptime_seconds': float((self.proc / 'uptime').read_text().split()[0]),
                  'host_memory_total': memory['MemTotal'], 'host_memory_available': memory.get('MemAvailable'),
                  'cgroup_memory_limit': None, 'cgroup_memory_current': None, 'cgroup_cpu_quota': None,
                  'cgroup_cpu_percent': None, 'network': network,
                  'root_filesystem': dict(zip(('total', 'used', 'free'), shutil.disk_usage('/')))}
        group = cgroup_directory(self.proc, self.sysfs)
        usage = None
        if group:
            for filename, key in (('memory.max', 'cgroup_memory_limit'), ('memory.current', 'cgroup_memory_current')):
                try:
                    value = (group / filename).read_text().strip()
                    result[key] = int(value) if value != 'max' else None
                except (OSError, ValueError):
                    pass
            try:
                quota, period = (group / 'cpu.max').read_text().split()
                result['cgroup_cpu_quota'] = int(quota) / int(period) if quota != 'max' else None
                stats = dict(line.split() for line in (group / 'cpu.stat').read_text().splitlines())
                usage = int(stats['usage_usec'])
            except (OSError, ValueError, KeyError, ZeroDivisionError):
                pass
        if self.previous:
            prior_time, prior_total, prior_idle, prior_network, prior_usage = self.previous
            elapsed, ticks = now - prior_time, total - prior_total
            if ticks > 0:
                result['cpu_percent'] = round(max(0, min(100, 100 * (1 - (idle - prior_idle) / ticks))), 2)
            if elapsed > 0:
                for interface, counters in network.items():
                    if interface in prior_network:
                        counters['rx_bytes_per_second'] = max(0, (counters['rx_bytes'] - prior_network[interface]['rx_bytes']) / elapsed)
                        counters['tx_bytes_per_second'] = max(0, (counters['tx_bytes'] - prior_network[interface]['tx_bytes']) / elapsed)
                if usage is not None and prior_usage is not None:
                    result['cgroup_cpu_percent'] = max(0, (usage - prior_usage) / (elapsed * 10000))
        self.previous = now, total, idle, network, usage
        return result


class History:
    def __init__(self, path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = path
        with closing(sqlite3.connect(path)) as connection:
            connection.execute('CREATE TABLE IF NOT EXISTS samples (time REAL PRIMARY KEY, data TEXT NOT NULL)')
            connection.commit()
        os.chmod(path, 0o600)

    def append(self, sample):
        with closing(sqlite3.connect(self.path)) as connection:
            connection.execute('INSERT OR REPLACE INTO samples VALUES (?, ?)', (sample['time'], json.dumps(sample)))
            connection.execute('DELETE FROM samples WHERE time NOT IN (SELECT time FROM samples ORDER BY time DESC LIMIT 10000)')
            connection.commit()

    def recent(self, limit=120):
        with closing(sqlite3.connect(self.path)) as connection:
            records = connection.execute('SELECT data FROM samples ORDER BY time DESC LIMIT ?', (min(1000, max(1, limit)),)).fetchall()
        return [json.loads(row[0]) for row in reversed(records)]


PAGE = b'''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Linux TUI Monitor</title><link rel="stylesheet" href="/style.css"><header><h1>Linux TUI Monitor</h1><button id="theme">Change theme</button><a href="/api/history">Download metrics JSON</a></header><main><section id="cards"></section><h2>CPU history</h2><svg id="chart" viewBox="0 0 600 120" role="img" aria-label="CPU usage history"><polyline id="line" fill="none" stroke="#58a6ff" stroke-width="2"/></svg><h2>Network interfaces</h2><pre id="network"></pre><p id="status">Loading...</p></main><script src="/app.js"></script></html>'''
STYLE = b'''body{font:16px system-ui;background:#101827;color:#e6edf3;margin:0 auto;padding:24px;max-width:1100px}body.light{background:#f5f7fa;color:#172033}header{display:flex;align-items:center;gap:20px;flex-wrap:wrap}a{color:#58a6ff}#cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:16px;margin:24px 0}.card{padding:20px;border:1px solid #708099;border-radius:12px}.value{font-size:28px;font-weight:600}svg{width:100%;background:#243047;border-radius:12px}pre{overflow:auto}button{padding:8px;border-radius:6px}'''
SCRIPT = b'''const cards=document.querySelector('#cards');document.querySelector('#theme').onclick=()=>document.body.classList.toggle('light');const fmt=x=>x==null?'Unavailable':(x/1073741824).toFixed(2)+' GiB';function card(label,value){const box=document.createElement('article');box.className='card';const title=document.createElement('div');title.textContent=label;const val=document.createElement('div');val.className='value';val.textContent=value;box.append(title,val);cards.append(box)}async function update(){try{const r=await fetch('/api/history');if(!r.ok)throw new Error('Authentication or collection failed');const history=await r.json();if(!history.length)return;const m=history.at(-1);cards.replaceChildren();card('Host CPU',m.cpu_percent==null?'Sampling...':m.cpu_percent+'%');card('Host available memory',fmt(m.host_memory_available));card('Cgroup memory usage / limit',fmt(m.cgroup_memory_current)+' / '+fmt(m.cgroup_memory_limit));card('Root filesystem free',fmt(m.root_filesystem.free));card('Uptime',(m.uptime_seconds/86400).toFixed(1)+' days');card('Cgroup CPU quota',m.cgroup_cpu_quota==null?'Unlimited / unknown':m.cgroup_cpu_quota+' CPUs');document.querySelector('#network').textContent=JSON.stringify(m.network,null,2);document.querySelector('#line').setAttribute('points',history.map((s,i)=>[i*600/Math.max(1,history.length-1),120-(s.cpu_percent||0)*1.2].join(',')).join(' '));document.querySelector('#status').textContent='Updated '+new Date(m.time*1000).toLocaleString()}catch(e){document.querySelector('#status').textContent=e.message}}update();setInterval(update,5000);'''


def token_file(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        if path.is_symlink() or path.stat().st_mode & 0o077:
            raise ValueError('Monitor token file must be a private regular file (chmod 600).')
        token = path.read_text().strip()
        if len(token) < 32:
            raise ValueError('Monitor token must contain at least 32 characters.')
        return token
    with os.fdopen(fd, 'w') as file:
        token = secrets.token_urlsafe(32)
        file.write(token + '\n')
    return token


def make_handler(history, token):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_GET(self):
            expected = 'Basic ' + base64.b64encode(('linux-tui:' + token).encode()).decode()
            received = self.headers.get('Authorization', '').encode()
            authorized = hmac.compare_digest(received, expected.encode()) or hmac.compare_digest(received, ('Bearer ' + token).encode())
            if not authorized:
                self.send_response(401)
                self.send_header('WWW-Authenticate', 'Basic realm="Linux TUI Monitor"')
                self.send_header('Content-Length', '0')
                self.end_headers()
                return
            routes = {'/': ('text/html; charset=utf-8', PAGE), '/style.css': ('text/css', STYLE), '/app.js': ('text/javascript', SCRIPT)}
            if self.path == '/api/history':
                payload, kind = json.dumps(history.recent()).encode(), 'application/json'
            elif self.path == '/api/metrics':
                recent = history.recent(1)
                payload, kind = json.dumps(recent[-1] if recent else {}).encode(), 'application/json'
            elif self.path in routes:
                kind, payload = routes[self.path]
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header('Content-Type', kind)
            self.send_header('Content-Length', str(len(payload)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Content-Security-Policy', "default-src 'self'; frame-ancestors 'none'; object-src 'none'; base-uri 'none'")
            self.end_headers()
            self.wfile.write(payload)
    return Handler


def serve(host='127.0.0.1', port=8008, state=DEFAULT_STATE):
    state = Path(state)
    token = token_file(state / 'monitor-token')
    history, collector = History(state / 'metrics.sqlite3'), Collector()
    history.append(collector.sample())
    stop = threading.Event()
    started = time.monotonic()
    def collect():
        consecutive = {}
        while not stop.wait(5):
            try:
                sample = collector.sample()
                history.append(sample)
                if time.monotonic() - started >= 300 and (state / 'notifications.json').is_file():
                    from .notifications import health_events, send_event
                    events = health_events(sample)
                    current = {event['title'] for event in events}
                    consecutive = {key: value for key, value in consecutive.items() if key in current}
                    for event in events:
                        consecutive[event['title']] = consecutive.get(event['title'], 0) + 1
                        if consecutive[event['title']] >= 3:
                            send_event(state, event)
            except (OSError, ValueError, KeyError, RuntimeError, sqlite3.Error):
                pass
    thread = threading.Thread(target=collect, daemon=True)
    server = ThreadingHTTPServer((host, port), make_handler(history, token))
    thread.start()
    print(f'Monitor: http://{host}:{port}\nLogin user: linux-tui\nPassword is stored in {state / "monitor-token"}\nFor remote use, connect through an SSH tunnel or an HTTPS reverse proxy.', flush=True)
    try:
        server.serve_forever()
    finally:
        stop.set()
        server.server_close()
        thread.join(timeout=6)
