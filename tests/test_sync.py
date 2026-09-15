import importlib.util
import json
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
    def test_recovery_migrates_previous_successful_inventory(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory)
            (state / 'last-applied.json').write_text(json.dumps({'groups': {
                'Keyboard': {'devices': ['Keyboard']}, 'RAM': {'devices': ['RAM', 'RAM']}}}))
            inventory = sync.parse_inventory('0: RAM\n Modes: Direct\n1: RAM\n Modes: Direct\n')
            self.assertEqual(sync.recovery_step(state, {}, inventory, 0)['missing'], ['Keyboard'])
            self.assertEqual(sync.recovery_step(state, {}, inventory, 15)['action'], 'rescan')

    def test_missing_device_recovery_is_staged_and_rearms_only_on_return(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory)
            full = sync.parse_inventory('0: Keyboard\n Modes: Direct\n1: RAM\n Modes: Direct\n2: RAM\n Modes: Direct\n')
            absent = full[1:]
            step = lambda inventory, now: sync.recovery_step(state, {}, inventory, now)
            self.assertEqual(step(full, 0)['missing'], [])
            self.assertTrue(step(absent, 1)['retry'])
            self.assertEqual(step(absent, 15)['action'], '')
            self.assertEqual(step(absent, 16)['action'], 'rescan')
            self.assertEqual(step(absent, 30)['action'], '')
            self.assertEqual(step(absent, 31)['action'], 'restart')
            for now in (32, 1000, 10000):
                result = step(absent, now)
                self.assertEqual(result['action'], '')
                self.assertFalse(result['retry'])
            step(full, 10001)
            step(absent, 10002)
            self.assertEqual(step(absent, 10017)['action'], 'rescan')
            # A rescan that recovers the device avoids a restart.
            self.assertEqual(step(full, 10032)['action'], '')

    def test_recovery_cooldown_counts_and_selection_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory)
            full = sync.parse_inventory('0: RAM\n Modes: Direct\n1: RAM\n Modes: Direct\n')
            single = sync.parse_inventory('0: RAM\n Modes: Direct\n')
            step = lambda inventory, now: sync.recovery_step(state, {}, inventory, now)
            step(full, 0)
            self.assertEqual(step(single, 1)['missing'], ['RAM'])
            step(single, 16)
            step(single, 31)
            step(full, 32)
            step(single, 33)
            self.assertEqual(step(single, 930)['action'], '')
            self.assertEqual(step(single, 931)['action'], 'rescan')
            result = sync.recovery_step(state, {'disabledDevices': ['RAM']}, single, 946)
            self.assertEqual(result['action'], '')
            self.assertEqual(result['missing'], [])
            step(full, 1000)
            result = sync.recovery_step(state, {'devices': []}, [], 1001)
            self.assertEqual(result['missing'], [])

    def test_recovery_requires_service_opt_in_and_invalidates_color_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            palette = home / '.local/state/omarchy/current/theme/colors.toml'
            palette.parent.mkdir(parents=True)
            palette.write_text('accent = "#123456"\n')
            with patch.dict(os.environ, {'HOME': directory, 'XDG_STATE_HOME': directory}), \
                 patch.object(sync.subprocess, 'run') as run, \
                 patch.object(sync, 'request_rescan') as rescan, \
                 patch.object(sync.time, 'time', return_value=0) as now:
                run.return_value.returncode = 0
                run.return_value.stdout = '0: Keyboard\n Modes: Direct\n1: RAM\n Modes: Direct\n'
                settings = {'managedServer': True}
                sync.apply(settings, allow_recovery=True)
                run.return_value.stdout = '0: RAM\n Modes: Direct\n'
                now.return_value = 1
                sync.apply(settings, allow_recovery=True)
                now.return_value = 16
                sync.apply(settings)  # Manual helper cannot initiate recovery.
                rescan.assert_not_called()
                result = sync.apply(settings, check=True, allow_recovery=True)
                self.assertEqual(result['recovery']['action'], 'rescan')
                rescan.assert_called_once()
                self.assertFalse((home / 'omarchy-rgb/last-applied.json').exists())
                now.return_value = 31
                result = sync.apply(settings, allow_recovery=True)
                self.assertEqual(result['recovery']['action'], 'restart')
                self.assertFalse((home / 'omarchy-rgb/last-applied.json').exists())
                result = sync.apply({}, allow_recovery=True)
                self.assertNotIn('recovery', result)

    def test_rescan_sdk_packet(self):
        with patch.object(sync.socket, 'create_connection') as connect:
            sync.request_rescan()
            connect.assert_called_once_with(('127.0.0.1', 6742), timeout=5)
            connect.return_value.__enter__.return_value.sendall.assert_called_once_with(
                b'ORGB\x00\x00\x00\x00\x8c\x00\x00\x00\x00\x00\x00\x00')

    def test_usb_return_rearms_cached_absence_without_bypassing_cooldown(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory)
            full = sync.parse_inventory('0: Keyboard\n Modes: Direct\n')
            sync.recovery_step(state, {}, full, 0)
            sync.recovery_step(state, {}, [], 1)
            sync.recovery_step(state, {}, [], 16)
            sync.recovery_step(state, {}, [], 31)
            self.assertFalse(sync.recovery_step(state, {}, [], 32, reconnect=True)['retry'])
            self.assertEqual(sync.recovery_step(state, {}, [], 930)['action'], '')
            self.assertEqual(sync.recovery_step(state, {}, [], 931)['action'], 'rescan')

    def test_automatic_discovery_groups_devices_and_falls_back_to_static(self):
        inventory = sync.parse_inventory("0: Keyboard\n  Type: Keyboard\n  Modes: [Direct] Static 'Color Wave'\n"
                                         "1: RAM\n  Type: DRAM\n  Modes: [Static]\n"
                                         "2: RAM\n  Type: DRAM\n  Modes: [Static]\n"
                                         "3: Unsupported\n  Modes: [Rainbow]\n")
        self.assertEqual(inventory[0]['modes'], ['Direct', 'Static', 'Color Wave'])
        self.assertEqual(inventory[1]['count'], 2)
        self.assertEqual(sync.select_devices({}, inventory), [{'name': 'Keyboard', 'mode': 'Direct'},
                                                              {'name': 'RAM', 'mode': 'Static'}])
        self.assertEqual(sync.select_devices({'disabledDevices': ['Keyboard']}, inventory),
                         [{'name': 'RAM', 'mode': 'Static'}])
        self.assertEqual(sync.select_devices({'disabledDevices': ['Keyboard', 'RAM']}, inventory), [])

    def test_pause_does_not_contact_hardware(self):
        with patch.object(sync.subprocess, 'run') as run:
            self.assertEqual(sync.apply({'paused': True})['status'], 'paused')
            run.assert_not_called()

    def test_device_failure_and_timeout_do_not_block_others_and_retry_independently(self):
        for failure in ('exit', 'timeout', 'mode'):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as directory:
                home = Path(directory)
                palette = home / '.local/state/omarchy/current/theme/colors.toml'
                palette.parent.mkdir(parents=True)
                palette.write_text('accent = "#123456"\n')
                settings = {'devices': [{'name': 'Keyboard', 'mode': 'Invalid' if failure == 'mode' else 'Direct'},
                                        {'name': 'Corsair RAM'}]}
                fail_keyboard = True

                def execute(command, **kwargs):
                    if '--list-devices' in command:
                        return subprocess.CompletedProcess(command, 0, '0: Keyboard\n  Modes: [Direct]\n1: Corsair RAM\n  Modes: [Direct]\n')
                    if 'Keyboard' in command and fail_keyboard:
                        if failure == 'timeout':
                            raise subprocess.TimeoutExpired(command, 15)
                        return subprocess.CompletedProcess(command, 1)
                    return subprocess.CompletedProcess(command, 0)

                with patch.dict(os.environ, {'HOME': directory, 'XDG_STATE_HOME': directory}), \
                     patch.object(sync.subprocess, 'run', side_effect=execute) as run:
                    result = sync.apply(settings)
                    self.assertEqual(result['status'], 'partial')
                    self.assertEqual(result['updated'], 1)
                    self.assertEqual(result['failures'][0]['device'], 'Keyboard')
                    run.reset_mock()
                    result = sync.apply(settings, check=True)
                    self.assertEqual(result['unchanged'], 1)
                    self.assertFalse(any('Corsair RAM' in call.args[0] for call in run.call_args_list))
                    fail_keyboard = False
                    settings['devices'][0]['mode'] = 'Direct'
                    run.reset_mock()
                    result = sync.apply(settings, check=True)
                    self.assertEqual(result['updated'], 1)
                    self.assertEqual(result['unchanged'], 1)
                    self.assertEqual(result['failures'], [])
                    self.assertFalse(any('Corsair RAM' in call.args[0] for call in run.call_args_list))

    def test_automatic_selector_cannot_reinclude_an_excluded_name(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            palette = home / '.local/state/omarchy/current/theme/colors.toml'
            palette.parent.mkdir(parents=True)
            palette.write_text('accent = "#123456"\n')
            with patch.dict(os.environ, {'HOME': directory, 'XDG_STATE_HOME': directory}), \
                 patch.object(sync.subprocess, 'run') as run:
                run.return_value.returncode = 0
                run.return_value.stdout = '0: RGB\n  Modes: [Direct]\n1: RGB Plus\n  Modes: [Direct]\n'
                result = sync.apply({'disabledDevices': ['RGB Plus']})
                self.assertEqual(run.call_count, 1)
                self.assertEqual(result['status'], 'failed')
                self.assertIn('excluded device', result['failures'][0]['error'])

    def test_managed_server_client_never_falls_back_to_local_detection(self):
        command = sync.build_command({'managedServer': True, 'devices': [{'name': 'Keyboard'}]}, '#123456')
        self.assertIn('--nodetect', command)
        self.assertNotIn('--noautoconnect', command)
        self.assertNotIn('--client', command)

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
                self.assertEqual(run.call_args.kwargs['timeout'], 15)
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
                self.assertIn('Failed: Keyboard: not currently detected', (home / 'omarchy-rgb/last-sync.log').read_text())

    def test_reconnect_and_resume_reapply_without_writing_on_every_poll(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            palette = home / '.local/state/omarchy/current/theme/colors.toml'
            palette.parent.mkdir(parents=True)
            palette.write_text('accent = "#123456"\n')
            settings = {'devices': [{'name': 'Keyboard'}, {'name': 'Corsair RAM'}]}
            with patch.dict(os.environ, {'HOME': directory, 'XDG_STATE_HOME': directory}), \
                 patch.object(sync.subprocess, 'run') as run:
                run.return_value.returncode = 0
                run.return_value.stdout = '0: Keyboard\n1: Corsair RAM\n2: Corsair RAM\n'
                sync.apply(settings)
                self.assertEqual(run.call_count, 3)
                run.reset_mock()
                sync.apply(settings, check=True)
                self.assertEqual(run.call_count, 1)  # discovery only
                run.reset_mock()
                sync.apply(settings)  # resume forces apply even if unchanged
                self.assertEqual(run.call_count, 3)
                run.return_value.stdout = '0: Corsair RAM\n1: Corsair RAM\n'
                run.reset_mock()
                sync.apply(settings, check=True)
                self.assertEqual(run.call_count, 1)  # healthy RAM is not rewritten
                run.return_value.stdout = '0: Keyboard\n1: Corsair RAM\n2: Corsair RAM\n'
                run.reset_mock()
                sync.apply(settings, check=True)
                self.assertEqual(run.call_count, 2)  # wireless keyboard returned
                run.return_value.stdout = '0: Keyboard\n1: Corsair RAM\n'
                run.reset_mock()
                sync.apply(settings, check=True)
                self.assertEqual(run.call_count, 2)  # duplicate count changed
                run.return_value.returncode = 1
                with self.assertRaises(RuntimeError):
                    sync.apply(settings, check=True)
                self.assertFalse((home / 'omarchy-rgb/last-applied.json').exists())
                run.return_value.returncode = 0
                run.reset_mock()
                sync.apply(settings, check=True)
                self.assertEqual(run.call_count, 3)  # retry after failed discovery


if __name__ == '__main__':
    unittest.main()
