#!/usr/bin/env python3
"""Apply the current Omarchy accent to explicitly selected OpenRGB devices."""
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


def apply(settings, check=False):
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
                command = build_command(settings, accent)
                inventory = subprocess.run(
                    connection_args(settings) + ['--list-devices'],
                    stdout=subprocess.PIPE, stderr=log, text=True, timeout=30, check=False)
                if inventory.returncode:
                    raise RuntimeError(f'OpenRGB device scan failed; see {log.name}')
                names = re.findall(r'^\d+: (.+)$', inventory.stdout, re.MULTILINE)
                available = []
                for device in settings['devices']:
                    if any(device['name'] in name for name in names):
                        available.append(device)
                    else:
                        log.write(f"Skipping unavailable device: {device['name']}\n")
                if not available:
                    (state / 'last-applied.json').unlink(missing_ok=True)
                    raise RuntimeError('None of the configured devices are currently detected')
                command = build_command(dict(settings, devices=available), accent)
                # Preserve duplicates: one of two identical RAM sticks may
                # disappear and return. Forced resume/USB syncs bypass this.
                selected_names = sorted(name for name in names if any(
                    device['name'] in name for device in available))
                fingerprint = {'command': command, 'devices': selected_names}
                cache = state / 'last-applied.json'
                try:
                    previous = json.loads(cache.read_text())
                except (OSError, ValueError):
                    previous = None
                if check and previous == fingerprint:
                    log.write('Selected devices and color unchanged; no lighting writes\n')
                    return
                # Never suppress retry after a failed or interrupted apply.
                cache.unlink(missing_ok=True)
                log.write(f'Applying accent {accent}\n')
                log.flush()
                result = subprocess.run(command, stdout=log, stderr=log, timeout=30, check=False)
                if result.returncode:
                    raise RuntimeError(f'OpenRGB exited with status {result.returncode}; see {log.name}')
                log.write('OpenRGB completed successfully\n')
                cache.write_text(json.dumps(fingerprint))
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
        apply(json.loads(args.settings), check=args.check)
    except (ValueError, OSError, RuntimeError, subprocess.TimeoutExpired) as error:
        print(error, file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
