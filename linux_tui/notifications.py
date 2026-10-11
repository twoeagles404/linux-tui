"""Explicitly configured notification channels, filtering and bounded delivery history."""
import hashlib
import json
from pathlib import Path
import smtplib
import ssl
import time
from email.message import EmailMessage
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

from .monitor import DEFAULT_STATE
from .workflows import atomic_write

CHANNELS = {
    'gotify': [('url', 'Gotify HTTPS base URL', False), ('token', 'Application token', True)],
    'discord': [('url', 'Discord HTTPS webhook URL', True)],
    'telegram': [('token', 'Telegram bot token', True), ('chat_id', 'Destination chat ID', False)],
    'pushover': [('token', 'Pushover application token', True), ('user', 'Pushover user key', True)],
    'email': [('host', 'SMTP host (TLS port 465)', False), ('user', 'SMTP username', False),
              ('password', 'SMTP password', True), ('sender', 'From address', False), ('recipient', 'To address', False)],
    'apprise': [('config', 'Absolute path to an existing private Apprise configuration file', False)],
}


def post(url, payload, headers=None, form=False):
    parsed = urlparse(url)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError('Notification endpoints must use HTTPS without embedded credentials.')
    body = urlencode(payload).encode() if form else json.dumps(payload).encode()
    request = Request(url, data=body, headers={'Content-Type': 'application/x-www-form-urlencoded' if form else 'application/json', **(headers or {})})
    try:
        with urlopen(request, timeout=15) as response:
            response.read(4096)
    except HTTPError as error:
        code = error.code
        error.close()
        raise RuntimeError(f'Notification endpoint returned HTTP {code}. Check local channel configuration.') from None
    except (URLError, TimeoutError, OSError):
        raise RuntimeError('Notification endpoint could not be reached. Check local channel configuration.') from None


def deliver(channel, config, title, message):
    if channel == 'gotify':
        post(config['url'].rstrip('/') + '/message', {'title': title, 'message': message, 'priority': 5}, {'X-Gotify-Key': config['token']})
    elif channel == 'discord':
        parsed = urlparse(config['url'])
        if parsed.hostname not in ('discord.com', 'discordapp.com') or not parsed.path.startswith('/api/webhooks/'):
            raise ValueError('Enter a Discord webhook URL.')
        post(config['url'], {'content': f'**{title}**\n{message}'[:1900]})
    elif channel == 'telegram':
        # Tokens appear only in the outbound request, never in error messages/history.
        import re
        if not re.fullmatch(r'\d+:[A-Za-z0-9_-]+', config['token']):
            raise ValueError('Invalid Telegram bot token format.')
        post('https://api.telegram.org/bot' + config['token'] + '/sendMessage', {'chat_id': config['chat_id'], 'text': f'{title}\n{message}'[:4000]})
    elif channel == 'pushover':
        post('https://api.pushover.net/1/messages.json', {'token': config['token'], 'user': config['user'], 'title': title, 'message': message[:1000]}, form=True)
    elif channel == 'email':
        email = EmailMessage()
        email['Subject'], email['From'], email['To'] = title, config['sender'], config['recipient']
        email.set_content(message)
        try:
            with smtplib.SMTP_SSL(config['host'], 465, context=ssl.create_default_context(), timeout=15) as smtp:
                smtp.login(config['user'], config['password'])
                smtp.send_message(email)
        except (OSError, smtplib.SMTPException):
            raise RuntimeError('SMTP delivery failed. Check local SMTP settings.') from None
    elif channel == 'apprise':
        import shutil
        import subprocess
        path = Path(config['config'])
        if not path.is_absolute() or not path.is_file() or path.is_symlink() or path.stat().st_mode & 0o077:
            raise ValueError('Apprise configuration must be an existing absolute private regular file (chmod 600).')
        if not shutil.which('apprise'):
            raise RuntimeError('Install Apprise first.')
        try:
            result = subprocess.run(['apprise', '--config', str(path), '--title', title, '--body', message],
                                    capture_output=True, timeout=30)
        except subprocess.TimeoutExpired:
            raise RuntimeError('Apprise delivery timed out.') from None
        if result.returncode:
            raise RuntimeError('Apprise delivery failed; review its local configuration.')
    else:
        raise ValueError('Unknown notification channel.')


def send_event(state, event, force=False):
    state = Path(state)
    config = json.loads((state / 'notifications.json').read_text())
    if event.get('severity', 'warning') not in config.get('severities', ['warning', 'critical']):
        return False
    history_path = state / 'notification-history.json'
    history = json.loads(history_path.read_text()) if history_path.exists() else []
    fingerprint = hashlib.sha256((event['title'] + '\n' + event['message']).encode()).hexdigest()
    now = time.time()
    successes = []
    for channel, settings in config['channels'].items():
        if not force and any(item['fingerprint'] == fingerprint and item['channel'] == channel and now - item['time'] < 3600 and item['ok'] for item in history):
            continue
        error = None
        try:
            deliver(channel, settings, event['title'], event['message'])
            successes.append(channel)
        except (ValueError, KeyError, RuntimeError, OSError) as failure:
            error = str(failure)
        history.append({'time': now, 'channel': channel, 'title': event['title'], 'severity': event.get('severity', 'warning'),
                        'fingerprint': fingerprint, 'ok': error is None, 'error': error})
    atomic_write(history_path, json.dumps(history[-500:], indent=2).encode())
    return bool(successes)


def health_events(sample):
    events = []
    cpu = sample.get('cpu_percent')
    if cpu is not None and cpu >= 90:
        events.append({'title': 'High host CPU usage', 'message': 'Host CPU usage is at or above 90%.', 'severity': 'warning'})
    disk = sample.get('root_filesystem', {})
    if disk.get('total') and disk.get('used', 0) / disk['total'] >= .9:
        events.append({'title': 'Root filesystem nearly full', 'message': 'Root filesystem usage is at or above 90%.', 'severity': 'critical'})
    limit, current = sample.get('cgroup_memory_limit'), sample.get('cgroup_memory_current')
    if limit and current is not None and current / limit >= .9:
        events.append({'title': 'Cgroup memory nearly full', 'message': 'This cgroup is using at or above 90% of its memory limit.', 'severity': 'critical'})
    return events


def notification_menu(ui):
    state = DEFAULT_STATE
    action = ui.menu('Notifications', [('configure', 'Configure a channel'), ('test', 'Send a test notification'),
                                      ('history', 'Delivery history'), ('disable', 'Disable all channels')])
    if not action:
        return
    path = state / 'notifications.json'
    config = json.loads(path.read_text()) if path.exists() else {'severities': ['warning', 'critical'], 'channels': {}}
    if action == 'configure':
        channel = ui.menu('Channel', [(key, key.capitalize()) for key in CHANNELS])
        if not channel:
            return
        settings = {}
        for key, label, secret in CHANNELS[channel]:
            value = ui.input('Configure ' + channel, label + ':', secret=secret)
            if not value:
                return
            settings[key] = value
        if ui.confirm('Save notification channel', f'Save {channel} credentials locally with private file permissions. No message is sent now. The web monitor sends threshold alerts after a five-minute startup grace period.'):
            config['channels'][channel] = settings
            atomic_write(path, json.dumps(config, indent=2).encode())
    elif action == 'test':
        if not config['channels']:
            raise ValueError('Configure a channel first.')
        if ui.confirm('Send test notification', 'Send “Linux TUI test” to these configured channels: ' + ', '.join(config['channels'])):
            success = send_event(state, {'title': 'Linux TUI test', 'message': 'Notification delivery test.', 'severity': 'warning'}, force=True)
            ui.message('Notification test', 'Delivered successfully.' if success else 'Delivery failed. See delivery history for details.')
    elif action == 'disable':
        if ui.confirm('Disable notifications', 'Remove all saved channel credentials from local configuration. Delivery history remains.'):
            config['channels'] = {}
            atomic_write(path, json.dumps(config).encode())
    else:
        history = state / 'notification-history.json'
        ui.message('Notification delivery history', history.read_text() if history.exists() else 'No notifications delivered.')
