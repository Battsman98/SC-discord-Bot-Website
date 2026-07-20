# HyperX to Discord Global Keybinds

This is a Windows AutoHotkey v2 setup for using HyperX headset/dongle buttons as Discord controls while Discord is in the background.

Important limitation: this does not reprogram the HyperX dongle firmware. It listens for headset controls that Windows exposes as keyboard/media/HID buttons, then sends Discord global keybinds.

## 1. Install AutoHotkey v2

Install AutoHotkey v2 from:

https://www.autohotkey.com/

Use AutoHotkey v2, not v1.

## 2. Configure Discord keybinds

In Discord desktop app:

1. Open `User Settings`.
2. Go to `Keybinds`.
3. Add these keybinds:

| Discord action | Keybind |
| --- | --- |
| Toggle Mute | `Ctrl+Left Shift+M` |
| Toggle Deafen | `Ctrl+Left Shift+D` |
| Push to Talk, optional | `Ctrl+Alt+Shift+F15` |

These keybinds are intentionally uncommon so they do not collide with games or apps.

Make sure Discord is running. Global keybinds only work in the desktop app, not reliably in browser Discord.

## 3. Find what your HyperX buttons emit

Run:

```powershell
.\tools\discord-hyperx\detect-hyperx-buttons.ahk
```

Press the HyperX headset/dongle buttons you want to use, then press `F12` to open AutoHotkey key history.

Look for recent entries such as:

- `Volume_Mute`
- `Volume_Up`
- `Volume_Down`
- `Media_Play_Pause`
- `Launch_App2`
- `vkXXscYYY`

If a button does not appear in key history, Windows may not expose it as a normal hotkey. In that case, it may be hardware-only and not scriptable without a lower-level HID tool.

## 4. Run the mapper

Run:

```powershell
.\tools\discord-hyperx\discord-hyperx-keybinds.ahk
```

Default mappings:

| Headset/Windows input | Sends to Discord |
| --- | --- |
| `vkB3` / media play-pause | `Ctrl+Left Shift+M` |
| `vkB0` / media next-track | `Ctrl+Left Shift+D` |
| `Launch_App2` | `Ctrl+Alt+Shift+F15` |

Edit `discord-hyperx-keybinds.ahk` if your headset exposes different button names or `vk/sc` codes.

## Notes

- If Discord is running as administrator, run this script as administrator too.
- If a game is running as administrator, run this script as administrator so it can still receive the headset button events.
- If you use the headset volume wheel for normal Windows volume, leave `Volume_Up` and `Volume_Down` unmapped.
- You can put a shortcut to `discord-hyperx-keybinds.ahk` in `shell:startup` to launch it with Windows.
