# Omarchy RGB Sync

Match your keyboard and PC lighting to the active Omarchy theme accent.
A small background service for Omarchy Quattro, powered by OpenRGB.

- Syncs when the shell starts and when the theme accent changes.
- Reapplies after resume and USB/HID changes, with delayed recovery attempts.
- Checks for wireless devices returning every 60 seconds without rewriting unchanged lighting.
- Automatically includes detected devices with Direct or Static lighting modes.
- Optional exclusions, explicit device selection, and brightness settings.
- Optional brightness scaling, including devices without a brightness control.
- Debounces rapid changes and serializes syncs.
- Applies each device name group independently, with a 15-second timeout per update.
- Retries failures without rewriting unchanged successful devices.
- Skips configured devices absent from a fresh OpenRGB scan.
- Optional local OpenRGB server for devices that restore onboard colors when OpenRGB exits.
- No bar widget, root process, or automatic package installation.

## Hardware compatibility

This plugin has been validated on a limited hardware setup, not across all
hardware. Compatibility depends on what your installed version of OpenRGB
supports and detects, including the device's connection type and available
lighting modes. The plugin does not add hardware support beyond OpenRGB.

Check `openrgb --noautoconnect --list-devices` for your own hardware before
configuring the plugin. See [Tested hardware](#tested-hardware) for the devices
used during development.

## Requirements

Omarchy Quattro with shell plugins, Python 3.11+, `dbus-monitor`, `udevadm`, and OpenRGB with working
user access to your hardware. Tested with Arch OpenRGB `1.0rc3-3`.
Hardware compatibility depends on OpenRGB and the connection type.

```bash
omarchy pkg add openrgb
openrgb --noautoconnect --list-devices
```

Confirm your devices appear and note their names and available modes.
Use OpenRGB's documented device access setup if they do not appear:
<https://openrgb.org/>. This plugin does not change device permissions.

## Install and configure

```bash
omarchy plugin add https://github.com/fewhnhouse/omarchy-rgb.git --enable
```

After installing OpenRGB and enabling the plugin, compatible detected devices
are selected automatically. You do not need to open a panel or copy device names.
The plugin uses Direct mode where supported and Static as a fallback. Devices
without either mode are left alone. Hardware access must already work in OpenRGB.

### Optional settings

To customize behavior, add fields to the plugin's existing entry in `plugins`
in `~/.config/omarchy/shell.json`. Preserve the rest of your configuration:

```json
{
  "id": "io.github.fewhnhouse.omarchy-rgb",
  "managedServer": true,
  "brightness": 100,
  "disabledDevices": [],
  "reconnectIntervalSec": 60
}
```

- `brightness`: 0–100, default 100. Scales RGB channel values.
- `disabledDevices`: exact names to exclude from automatic selection.
- `reconnectIntervalSec`: wireless discovery interval, default 60, minimum 15.
- `managedServer`: keeps OpenRGB running locally; see below. Default false.
- `paused`: stops automatic updates without changing the current lights. Default false.

For explicit selection or a different mode, supply a `devices` array instead:

```json
{
  "id": "io.github.fewhnhouse.omarchy-rgb",
  "devices": [
    { "name": "G515 LS TKL", "mode": "Direct" },
    { "name": "Corsair Dominator Platinum RGB DDR5", "mode": "Direct" }
  ]
}
```

An explicit `devices` list disables automatic selection unless `autoDetect` is
set to true. Remove the list to return to automatic selection. An empty explicit
list selects nothing. Modes must be supported by the matched hardware.

OpenRGB name selectors match substrings. Use full names to avoid selecting
unrelated devices. Identical names form one group (for example, both RAM sticks),
so failure isolation is between name groups, not between individual LEDs or
identically named devices. A selector that would also match an excluded device
is skipped and logged. Numeric selectors are rejected because enumeration order
can change. Settings reload when shell.json changes.

### Keyboard colors revert after a while

Some devices need OpenRGB to remain running to retain software lighting control.
The Logitech HID++ driver in OpenRGB 1.0rc3 releases software control and restores
firmware mode when its owning process shuts down. For these devices, add
`"managedServer": true` to the plugin entry. The service starts one background
OpenRGB server bound to `127.0.0.1:6742`, and the helper connects through OpenRGB's
default local-server discovery without local hardware detection. Port 6742 must
be available before enabling this option.
The plugin owns this process and stops it when disabled; no system service is installed.

Do not run another OpenRGB instance or the old standalone hook alongside this
option. A persistent connection avoids releasing control after every command;
actual sleep/wake behavior still depends on the device and OpenRGB driver.

## Behavior and limitations

The helper reads `~/.local/state/omarchy/current/theme/colors.toml` after taking
its lock. Theme accent changes during a running sync queue another run using
the latest settings and palette. It writes its lock, latest log, and last
successfully applied device/color snapshot under
`${XDG_STATE_HOME:-~/.local/state}/omarchy-rgb/`.

Each sync scans devices once (30-second timeout), then updates each selected
name group separately (15-second timeout per group). A missing device, invalid
mode, nonzero exit, or timeout is recorded without blocking other groups.
The log and helper result identify partial failures. Periodic checks retry failed
groups while retaining successful groups in the cache; unchanged successful
lighting is not rewritten. A discovery failure prevents updates for that run.

Resume signals from logind and USB/HID events trigger recovery after 2 seconds
and again after 15 seconds to allow controllers to initialize. Periodic discovery
catches wireless devices whose receiver stays plugged in. Discovery compares
each selected name group (including duplicate counts), settings, and colors with
its last successful apply; unchanged lighting is not rewritten. A device that
resets internally without an event or any detectable absence cannot be identified
by discovery alone. Toggle the plugin off/on to force an update in that case.

No device profiles are saved. Disabling the plugin stops future updates; lights
retain the last applied color according to their firmware.
Avoid running another RGB application or an old theme hook that controls the
same devices at the same time.

If you installed the earlier standalone hook, remove its two installed copies
when switching to this plugin:

```bash
rm ~/.config/omarchy/hooks/theme-set.d/omarchy-rgb-sync
rm ~/.config/omarchy/hooks/post-boot.d/omarchy-rgb-sync
```

## Tested hardware

The original hook was visually confirmed on Logitech G515 LS TKL, two Corsair
Dominator Platinum RGB DDR5 sticks, and Gigabyte RTX 4070 SUPER GAMING OC.
The plugin uses the same OpenRGB commands with configurable device selectors.
Testing was limited to this setup. Compatibility with other hardware depends
on OpenRGB support and has not been verified by this project.

## Troubleshooting

Read `~/.local/state/omarchy-rgb/last-sync.log` (under `$XDG_STATE_HOME` if set).
Missing dependencies, malformed settings, unsupported modes, and device access
errors are reported there and in the shell log. An OpenRGB exit code of zero
means the command completed, not proof that every physical LED changed.

For a manual run from a checkout using the local managed server:

```bash
python3 sync.py --settings '{"managedServer":true}'
```

## Update or remove

```bash
omarchy plugin update io.github.fewhnhouse.omarchy-rgb
omarchy plugin remove io.github.fewhnhouse.omarchy-rgb
```

Removal stops automatic syncing. The diagnostic log remains in your state
folder; OpenRGB remains installed for other uses.

## Development

```bash
python3 -m unittest discover -s tests -v
python3 tests/smoke_service.py
omarchy plugin validate .
```

MIT licensed. Independent community plugin; not affiliated with Omarchy,
OpenRGB, or hardware manufacturers.
