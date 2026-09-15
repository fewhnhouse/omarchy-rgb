# Omarchy RGB Sync

Match your keyboard and PC lighting to the active Omarchy theme accent.
A small background service for Omarchy Quattro, powered by OpenRGB.

- Syncs when the shell starts and when the theme accent changes.
- Reapplies after resume and USB/HID changes, with delayed recovery attempts.
- Checks for wireless devices returning every 60 seconds without rewriting unchanged lighting.
- Select devices by name, with a separate OpenRGB mode for each device.
- Optional brightness scaling, including devices without a brightness control.
- Debounces rapid changes, serializes calls, and limits OpenRGB runs to 30 seconds.
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

Manual setup is required: add `devices` to this plugin's existing entry in
`plugins` in `~/.config/omarchy/shell.json`. Keep the rest of your config intact.
No devices are controlled until you choose them. Example:

```json
{
  "id": "io.github.fewhnhouse.omarchy-rgb",
  "brightness": 100,
  "devices": [
    { "name": "G515 LS TKL", "mode": "Direct" },
    { "name": "Corsair Dominator Platinum RGB DDR5", "mode": "Direct" },
    { "name": "Gigabyte GeForce RTX 4070 SUPER GAMING OC", "mode": "Direct" }
  ]
}
```

Replace these example names with your hardware. OpenRGB name selectors match
substrings, so use full names to avoid selecting unrelated devices. Identical
names select all matching devices (for example, both RAM sticks). Numeric device
indices are intentionally rejected because enumeration order can change.

`mode` defaults to `Direct`; use a mode reported by your device, such as `Static`,
if Direct is unavailable. Brightness is a percentage from 0 to 100, applied to
RGB channel values. The default is 100. Settings reload with the shell config.
`reconnectIntervalSec` controls wireless device discovery (default 60, minimum 15).

### Keyboard colors revert after a while

Some devices need OpenRGB to remain running to retain software lighting control.
The Logitech HID++ driver in OpenRGB 1.0rc3 releases software control and restores
firmware mode when its owning process shuts down. For these devices, add
`"managedServer": true` to the plugin entry. The service starts one background
OpenRGB server bound to `127.0.0.1:6743`, and the helper connects to it without
local hardware detection. `serverPort` can select a different unused port.
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

Each sync scans devices, then applies the color to available selections. Each
OpenRGB process has a 30-second timeout (up to 60 seconds total). A device that
disconnects between scanning and applying can still cause OpenRGB to report an
error; the next theme change or plugin restart tries again.

Resume signals from logind and USB/HID events trigger recovery after 2 seconds
and again after 15 seconds to allow controllers to initialize. Periodic discovery
catches wireless devices whose receiver stays plugged in. Discovery compares
selected device names (including duplicate counts), settings, and colors with
the last successful apply; unchanged lighting is not rewritten. A device that
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

For a manual run from a checkout:

```bash
python3 sync.py --settings '{"devices":[{"name":"G515 LS TKL","mode":"Direct"}]}'
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
