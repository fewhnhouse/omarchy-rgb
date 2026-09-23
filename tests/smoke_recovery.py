"""Exercise real QML rescan/restart orchestration with an isolated fake server."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

source = Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix='rgb-recovery-') as directory:
    root = Path(directory)
    (root / 'Commons').symlink_to(Path(os.environ.get('OMARCHY_PATH', '/usr/share/omarchy')) / 'shell/Commons')
    (root / 'runtime').mkdir(mode=0o700)
    (root / 'bin').mkdir()
    service = (source / 'Service.qml').read_text()
    for name in ('openrgb', 'dbus-monitor', 'udevadm'):
        service = service.replace('/usr/bin/' + name, str(root / 'bin' / name))
    (root / 'Service.qml').write_text(service)
    config = root / '.config/omarchy/shell.json'
    config.parent.mkdir(parents=True)
    config.write_text(json.dumps({'plugins': [{'id': 'io.github.fewhnhouse.omarchy-rgb', 'managedServer': True}]}))
    (root / 'sync.py').write_text('''import json, os, sys, time
from pathlib import Path
root = Path(os.environ['HOME'])
with (root / 'workers').open('a') as log:
    log.write(str(time.time()) + '\\n')
assert '--allow-recovery' in sys.argv
count = len((root / 'workers').read_text().splitlines())
print(json.dumps({'recovery': {'action': 'rescan' if count == 1 else 'restart' if count == 2 else '', 'retry': False}}))
''')
    programs = {
        'openrgb': '''#!/usr/bin/env python3
import os, signal, time
from pathlib import Path
log = Path(os.environ['HOME']) / 'servers'
def record(event):
    with log.open('a') as output:
        output.write(event + ' ' + str(os.getpid()) + '\\n')
def stop(*args):
    record('stop')
    raise SystemExit(0)
signal.signal(signal.SIGTERM, stop)
record('start')
while True: time.sleep(1)
''',
        'dbus-monitor': '#!/bin/sh\nsleep 60\n',
        'udevadm': '#!/bin/sh\nsleep 60\n',
    }
    for name, content in programs.items():
        path = root / 'bin' / name
        path.write_text(content)
        path.chmod(0o755)
    (root / 'shell.qml').write_text('''import QtQuick
import Quickshell
ShellRoot {
  Loader { source: "Service.qml" }
  Timer { interval: 32000; running: true; onTriggered: Qt.quit() }
}
''')
    env = dict(os.environ, HOME=directory, XDG_RUNTIME_DIR=str(root / 'runtime'),
               QT_QPA_PLATFORM='offscreen', QT_QPA_PLATFORMTHEME='', QT_QUICK_CONTROLS_STYLE='Basic',
               PATH=str(root / 'bin') + ':' + os.environ['PATH'])
    result = subprocess.run(['quickshell', '--no-color', '-p', str(root / 'shell.qml')],
                            env=env, capture_output=True, text=True, timeout=40)
    assert result.returncode == 0, result.stdout + result.stderr
    calls = [float(line) for line in (root / 'workers').read_text().splitlines()]
    events = (root / 'servers').read_text().splitlines()
    assert len(calls) >= 3, (calls, events, result.stdout, result.stderr)
    assert calls[1] - calls[0] >= 15, calls  # No writes during rescan settling.
    assert calls[2] - calls[1] >= 10, calls  # Wait for owned server restart.
    assert sum(line.startswith('start ') for line in events) == 2, events
    assert events[1] == 'stop ' + events[0].split()[1], events
    print('PASS: rescan settling, owned-process restart, and color reapply scheduling')
