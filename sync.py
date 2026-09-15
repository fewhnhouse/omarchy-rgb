#!/usr/bin/env python3
"""Apply the current Omarchy accent to discovered or explicitly selected OpenRGB devices."""
import argparse
from datetime import datetime
import fcntl
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import tomllib


def connection_args(settings):
    if settings.get('managedServer', False) is not True:
        return ['openrgb', '--noautoconnect']
    # Never fall back to local detection when the server is unavailable: a
    # second process can release firmware control when it exits. OpenRGB's
    # auto-connect path waits for remote enumeration; --client in 1.0rc3 does
    # not, so explicit --client + --nodetect can return an incomplete list.
    return ['openrgb', '--nodetect']


def build_command(settings, accent):
    if not isinstance(settings, dict):
        raise ValueError('Settings must be a JSON object')
    if not isinstance(accent, str) or not re.fullmatch(r'#[0-9a-fA-F]{6}', accent):
        raise ValueError('Theme accent must be a six-digit hex color')
    devices = settings.get('devices', [])
    if not isinstance(devices, list):
        raise ValueError('devices must be an array')
    if not devices:
        raise ValueError('Configure devices in the plugin entry in ~/.config/omarchy/shell.json; see README')
    brightness = settings.get('brightness', 100)
    if type(brightness) not in (int, float) or not 0 <= brightness <= 100:
        raise ValueError('brightness must be a number from 0 to 100')
    color = ''.join(f'{round(int(accent[i:i + 2], 16) * brightness / 100):02x}' for i in (1, 3, 5))
    command = connection_args(settings)
    for device in devices:
        if not isinstance(device, dict):
            raise ValueError('Each device must be an object with a name and optional mode')
        name, mode = device.get('name'), device.get('mode', 'Direct')
        # OpenRGB supports substring names (at least three characters). Reject
        # numeric selectors so device ordering changes cannot retarget lights.
        if not isinstance(name, str) or len(name.strip()) < 3 or name.isdecimal() or name.startswith('-'):
            raise ValueError('Device name must be a name of at least three characters, not an index or option')
        if not isinstance(mode, str) or not mode.strip() or mode.startswith('-'):
            raise ValueError('Device mode must be a nonempty mode name')
        command += ['--device', name, '--mode', mode, '--color', color]
    return command


def parse_inventory(text):
    """Group identical names, retaining the count and common supported modes."""
    found = []
    current = None
    for line in text.splitlines():
        match = re.match(r'^\d+: (.+)$', line)
        if match:
            current = {'name': match[1], 'type': 'Device', 'modes': []}
            found.append(current)
        elif current and line.strip().startswith('Type:'):
            current['type'] = line.split(':', 1)[1].strip()
        elif current and line.strip().startswith('Modes:'):
            current['modes'] = [token.strip("[]'\"") for token in re.findall(
                r"\[[^\]]+\]|'[^']*'|\S+", line.split(':', 1)[1])]
    grouped = {}
    for device in found:
        name = device['name']
        if name not in grouped:
            grouped[name] = dict(device, count=1)
        else:
            grouped[name]['count'] += 1
            grouped[name]['modes'] = [mode for mode in grouped[name]['modes'] if mode in device['modes']]
    for device in grouped.values():
        device['defaultMode'] = next((mode for mode in ('Direct', 'Static') if mode in device['modes']), '')
    return list(grouped.values())


def select_devices(settings, inventory):
    automatic = settings.get('autoDetect', 'devices' not in settings)
    disabled = settings.get('disabledDevices', [])
    if not isinstance(disabled, list) or not all(isinstance(name, str) for name in disabled):
        raise ValueError('disabledDevices must be an array of names')
    if automatic:
        devices = [{'name': device['name'], 'mode': device['defaultMode']}
                   for device in inventory if device['defaultMode'] and device['name'] not in disabled]
    else:
        devices = settings.get('devices', [])
        if not isinstance(devices, list):
            raise ValueError('devices must be an array')
    return devices


def apply(settings, check=False):
    if not isinstance(settings, dict):
        raise ValueError('Settings must be a JSON object')
    if settings.get('paused', False):
        return {'status': 'paused', 'message': 'Automatic syncing paused'}
    state = Path(os.environ.get('XDG_STATE_HOME') or Path.home() / '.local/state') / 'omarchy-rgb'
    state.mkdir(parents=True, exist_ok=True)
    with (state / 'sync.lock').open('w') as lock:
        deadline = time.monotonic() + 45
        while True:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise TimeoutError('Timed out waiting for another RGB sync')
                time.sleep(0.1)
        with (state / 'last-sync.log').open('w') as log:
            log.write(datetime.now().astimezone().isoformat() + '\n')
            try:
                palette = Path.home() / '.local/state/omarchy/current/theme/colors.toml'
                with palette.open('rb') as source:
                    accent = tomllib.load(source).get('accent')
                inventory_result = subprocess.run(
                    connection_args(settings) + ['--list-devices'],
                    stdout=subprocess.PIPE, stderr=log, text=True, timeout=30, check=False)
                if inventory_result.returncode:
                    raise RuntimeError(f'OpenRGB device scan failed; see {log.name}')
                inventory = parse_inventory(inventory_result.stdout)
                requested = select_devices(settings, inventory)
                # Validate shared settings once. Device-specific validation is
                # inside the loop so one invalid mode/name cannot block others.
                build_command(dict(settings, devices=[{'name': 'validation'}]), accent)
                cache = state / 'last-applied.json'
                try:
                    previous = json.loads(cache.read_text())
                    previous = previous.get('groups', {}) if isinstance(previous, dict) else {}
                    if not isinstance(previous, dict):
                        previous = {}
                except (OSError, ValueError):
                    previous = {}
                # Invalidate before writing hardware. A crash must not leave an
                # old successful snapshot that suppresses the next retry.
                cache.unlink(missing_ok=True)
                successful = {}
                failures = []
                updated = 0
                unchanged = 0
                attempted = set()
                for device in requested:
                    label = str(device.get('name', '<missing name>')) if isinstance(device, dict) else repr(device)
                    if label in attempted:
                        continue
                    attempted.add(label)
                    try:
                        command = build_command(dict(settings, devices=[device]), accent)
                        matches = [found for found in inventory if device['name'] in found['name']]
                        if not matches:
                            raise ValueError('not currently detected')
                        # Automatic exclusions must not be defeated by the
                        # CLI's substring matching (e.g. "RGB" vs "RGB Plus").
                        if any(found['name'] in settings.get('disabledDevices', []) for found in matches):
                            raise ValueError('name also matches an excluded device; skipping this selector')
                        mode = device.get('mode', 'Direct')
                        if any(found['modes'] and mode not in found['modes'] for found in matches):
                            raise ValueError(f'mode {mode!r} is not supported by every matching device')
                        fingerprint = {'command': command, 'devices': sorted(
                            found['name'] for found in matches for _ in range(found['count']))}
                        count = sum(found['count'] for found in matches)
                        if check and previous.get(label) == fingerprint:
                            successful[label] = fingerprint
                            unchanged += count
                            log.write(f'Unchanged: {label}\n')
                            continue
                        log.write(f'Applying accent {accent} to {label}\n')
                        log.flush()
                        result = subprocess.run(command, stdout=log, stderr=log, timeout=15, check=False)
                        if result.returncode:
                            raise RuntimeError(f'OpenRGB exited with status {result.returncode}')
                        successful[label] = fingerprint
                        updated += count
                        log.write(f'Updated: {label}\n')
                    except (ValueError, OSError, RuntimeError, subprocess.TimeoutExpired) as error:
                        failures.append({'device': label, 'error': str(error)})
                        log.write(f'Failed: {label}: {error}\n')
                cache.write_text(json.dumps({'groups': successful}))
                status = ('partial' if successful else 'failed') if failures else ('synced' if updated else 'unchanged')
                if not requested:
                    status = 'idle'
                summary = {'status': status, 'updated': updated, 'unchanged': unchanged, 'failures': failures}
                log.write(json.dumps(summary) + '\n')
                return summary
            except Exception as error:
                (state / 'last-applied.json').unlink(missing_ok=True)
                log.write(f'Error: {error}\n')
                raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--settings', default='{}', help='Inline plugin settings as JSON')
    parser.add_argument('--check', action='store_true', help='Only apply if selected devices or colors changed')
    args = parser.parse_args()
    try:
        result = apply(json.loads(args.settings), check=args.check)
        print(json.dumps(result))
        if result.get('failures'):
            print('; '.join(f"{failure['device']}: {failure['error']}" for failure in result['failures']), file=sys.stderr)
            return 1
    except (ValueError, OSError, RuntimeError, subprocess.TimeoutExpired) as error:
        print(error, file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
