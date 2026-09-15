# Omarchy RGB Sync

Match your keyboard and PC lighting to the active Omarchy theme accent.
A small background service for Omarchy Quattro, powered by OpenRGB.

- Syncs when the shell starts and when the theme accent changes.
- Select devices by name, with a separate OpenRGB mode for each device.
- Optional brightness scaling, including devices without a brightness control.
- Debounces rapid changes, serializes calls, and limits OpenRGB runs to 30 seconds.
- Skips configured devices absent from a fresh OpenRGB scan.
- No bar widget, OpenRGB server, root process, or automatic package installation.

## Known limitation: NZXT N7 Z790

**Lighting connected through the NZXT N7 Z790 motherboard controller is not
currently supported by this plugin in our tested setup.** OpenRGB `1.0rc3-3`
did not detect that controller (USB ID `1e71:201d`), so the plugin cannot sync
fans or LED strips connected through it. Support remains unresolved; there is
no confirmed workaround in this project yet.

The keyboard, Corsair RGB RAM, and Gigabyte GPU were detected independently
and can still sync on that motherboard. This limitation concerns the N7 Z790
controller tested here; compatibility with other NZXT devices has not been
verified by this project. Check `openrgb --noautoconnect --list-devices` for
your own hardware before configuring the plugin.

## Requirements

Omarchy Quattro with shell plugins, Python 3.11+, and OpenRGB with working
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

## Behavior and limitations

The helper reads `~/.local/state/omarchy/current/theme/colors.toml` after taking
its lock. Theme accent changes during a running sync queue another run using
the latest settings and palette. It writes only its lock and latest log under
`${XDG_STATE_HOME:-~/.local/state}/omarchy-rgb/`.

Each sync scans devices, then applies the color to available selections. Each
OpenRGB process has a 30-second timeout (up to 60 seconds total). A device that
disconnects between scanning and applying can still cause OpenRGB to report an
error; the next theme change or plugin restart tries again.

No device profiles are saved. Disabling the plugin stops future updates; lights
retain the last applied color according to their firmware. There is no reconnect
or resume watcher in this version. Toggle the plugin off/on to reapply if needed.
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
For the motherboard controller, see [Known limitation: NZXT N7 Z790](#known-limitation-nzxt-n7-z790).
Other hardware has not been verified by this project.

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
omarchy plugin validate .
```

MIT licensed. Independent community plugin; not affiliated with Omarchy,
OpenRGB, or hardware manufacturers.
