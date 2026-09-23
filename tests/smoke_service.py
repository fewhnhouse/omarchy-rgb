"""Run the real QML service against fake devices and simulated sleep/USB events."""
from pathlib import Path
import json
import os
import shutil
import subprocess
import tempfile
import threading

if not shutil.which('quickshell'):
    raise SystemExit('quickshell is required for this integration test')
source = Path(__file__).resolve().parents[1]
commons = Path(os.environ.get('OMARCHY_PATH', '/usr/share/omarchy')) / 'shell/Commons'
with tempfile.TemporaryDirectory(prefix='rgb-service-') as directory:
    root = Path(directory)
    (root / 'Commons').symlink_to(commons, target_is_directory=True)
    (root / 'runtime').mkdir(mode=0o700)
    (root / 'bin').mkdir()
    service = (source / 'Service.qml').read_text()
    for name in ('openrgb', 'dbus-monitor', 'udevadm'):
        service = service.replace('/usr/bin/' + name, str(root / 'bin' / name))
    (root / 'Service.qml').write_text(service)
    (root / 'sync.py').write_text((source / 'sync.py').read_text().replace(
        "OPENRGB = '/usr/bin/openrgb'", f"OPENRGB = {str(root / 'bin' / 'openrgb')!r}"))
    palette = root / '.local/state/omarchy/current/theme/colors.toml'
    palette.parent.mkdir(parents=True)
    palette.write_text('accent = "#4080c0"\n')
    config = root / '.config/omarchy/shell.json'
    config.parent.mkdir(parents=True)
    config.write_text(json.dumps({'plugins': [{'id': 'io.github.fewhnhouse.omarchy-rgb',
                                              'devices': [{'name': 'Test Keyboard'}]}]}))
    programs = {
        'openrgb': '''#!/usr/bin/env python3
import json, os, sys, time
if '--list-devices' in sys.argv:
    print('0: Test Keyboard\\n  Modes: [Direct] Static')
else:
    with open(os.path.join(os.environ['HOME'], 'calls.jsonl'), 'a') as log:
        log.write(json.dumps({'time': time.time(), 'args': sys.argv[1:]})+'\\n')
''',
        'dbus-monitor': '#!/bin/sh\nsleep 1\necho "   boolean true"\nsleep 1\necho "   boolean false"\nsleep 30\n',
        'udevadm': '#!/bin/sh\nsleep 5\necho "UDEV  [100.123] add /devices/test (hidraw)"\nsleep 30\n',
    }
    for name, program in programs.items():
        target = root / 'bin' / name
        target.write_text(program)
        target.chmod(0o755)
    (root / 'shell.qml').write_text('''import QtQuick
import Quickshell
ShellRoot {
  Loader {
    id: plugin
    source: "%s"
  }
  Timer { interval: 10000; running: true; onTriggered: Qt.quit() }
}
''' % (root / 'Service.qml').as_uri())
    env = dict(os.environ, HOME=directory, XDG_STATE_HOME=str(root / '.local/state'),
               XDG_RUNTIME_DIR=str(root / 'runtime'), QT_QPA_PLATFORM='offscreen',
               QT_QPA_PLATFORMTHEME='', QT_QUICK_CONTROLS_STYLE='Basic',
               PATH=str(root / 'bin') + ':' + os.environ['PATH'])
    def change_settings():
        updated = config.with_suffix('.tmp')
        updated.write_text(json.dumps({'plugins': [{'id': 'io.github.fewhnhouse.omarchy-rgb',
                                                   'devices': [{'name': 'Test Keyboard'}], 'brightness': 50}]}))
        updated.replace(config)
    change = threading.Timer(1.2, change_settings)
    change.start()
    result = subprocess.run(['quickshell', '--no-color', '-p', str(root / 'shell.qml')],
                            env=env, capture_output=True, text=True, timeout=15)
    change.join()
    assert result.returncode == 0, result.stdout + result.stderr
    calls = [json.loads(line) for line in (root / 'calls.jsonl').read_text().splitlines()]
    assert len(calls) == 3, (calls, result.stdout, result.stderr)
    assert calls[0]['args'][-1] == '4080c0', calls
    assert calls[1]['args'][-1] == calls[2]['args'][-1] == '204060', calls
    assert calls[1]['time'] - calls[0]['time'] >= 3, calls
    assert calls[2]['time'] - calls[1]['time'] >= 2, calls
    print('PASS: startup, deferred update during sleep, resume recovery, and USB reconnect recovery')
