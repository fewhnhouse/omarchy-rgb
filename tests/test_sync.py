import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('rgb_sync', Path(__file__).resolve().parents[1] / 'sync.py')
sync = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sync)


class SyncTests(unittest.TestCase):
    def test_names_are_literal_arguments_and_modes_are_per_device(self):
        settings = {'devices': [{'name': 'Keyboard $(touch nope)'}, {'name': 'RAM', 'mode': 'Static'}]}
        command = sync.build_command(settings, '#3264eb')
        self.assertEqual(command, ['openrgb', '--noautoconnect', '--device', 'Keyboard $(touch nope)',
                                  '--mode', 'Direct', '--color', '3264eb', '--device', 'RAM',
                                  '--mode', 'Static', '--color', '3264eb'])

    def test_brightness_scales_channels(self):
        settings = {'devices': [{'name': 'Keyboard'}], 'brightness': 50}
        self.assertEqual(sync.build_command(settings, '#3264ec')[-1], '193276')
        settings['brightness'] = 0
        self.assertEqual(sync.build_command(settings, '#3264ec')[-1], '000000')

    def test_invalid_settings_do_not_build_a_command(self):
        for settings in [{}, [], {'devices': 'all'}, {'devices': ['Keyboard']},
                         {'devices': [{'name': '123'}]}, {'devices': [{'name': '--all'}]},
                         {'devices': [{'name': 'Keyboard', 'mode': '--off'}]},
                         {'devices': [{'name': 'Keyboard'}], 'brightness': True},
                         {'devices': [{'name': 'Keyboard'}], 'brightness': 101}]:
            with self.subTest(settings=settings), self.assertRaises(ValueError):
                sync.build_command(settings, '#123456')
        with self.assertRaises(ValueError):
            sync.build_command({'devices': [{'name': 'Keyboard'}]}, '#xyz123')

    def test_apply_reads_palette_and_reports_process_failures(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            palette = home / '.local/state/omarchy/current/theme/colors.toml'
            palette.parent.mkdir(parents=True)
            palette.write_text('accent = "#123456"\n')
            with patch.dict(os.environ, {'HOME': directory, 'XDG_STATE_HOME': directory}), \
                 patch.object(sync.subprocess, 'run') as run:
                run.return_value.returncode = 0
                run.return_value.stdout = '0: Keyboard\n  Type: Keyboard\n'
                sync.apply({'devices': [{'name': 'Keyboard'}]})
                self.assertEqual(run.call_args.args[0][-1], '123456')
                self.assertEqual(run.call_args.kwargs['timeout'], 30)
                run.return_value.returncode = 1
                with self.assertRaises(RuntimeError):
                    sync.apply({'devices': [{'name': 'Keyboard'}]})
                self.assertIn('scan failed', (home / 'omarchy-rgb/last-sync.log').read_text())
                run.side_effect = subprocess.TimeoutExpired('openrgb', 30)
                with self.assertRaises(subprocess.TimeoutExpired):
                    sync.apply({'devices': [{'name': 'Keyboard'}]})
                self.assertIn('timed out', (home / 'omarchy-rgb/last-sync.log').read_text())

    def test_missing_keyboard_does_not_block_ram(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            palette = home / '.local/state/omarchy/current/theme/colors.toml'
            palette.parent.mkdir(parents=True)
            palette.write_text('accent = "#123456"\n')
            with patch.dict(os.environ, {'HOME': directory, 'XDG_STATE_HOME': directory}), \
                 patch.object(sync.subprocess, 'run') as run:
                run.return_value.returncode = 0
                run.return_value.stdout = '0: Corsair RAM\n1: Corsair RAM\n'
                sync.apply({'devices': [{'name': 'Keyboard'}, {'name': 'Corsair RAM'}]})
                self.assertNotIn('Keyboard', run.call_args.args[0])
                self.assertIn('Corsair RAM', run.call_args.args[0])
                self.assertIn('Skipping unavailable device: Keyboard', (home / 'omarchy-rgb/last-sync.log').read_text())


if __name__ == '__main__':
    unittest.main()
