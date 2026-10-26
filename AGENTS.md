# AGENTS.md

Notes for coding agents (and people) working on this repo.

## What this is

Ableton Push 2 as a Traktor Pro 4 controller on macOS. Traktor can only light a
controller LED on or off, so a small Python bridge sits in the middle and draws
the pads itself:

```
Push 2 (User port)  ⇄  push_quad.py / push_bridge.py  ⇄  virtual port "Push2 Traktor Bridge"  ⇄  Traktor
```

The bridge turns Push presses into notes/CCs from `contract.py`. Traktor sends
state back on the same addresses (play on, hotcue type, beat phase…), and the
bridge renders colours and animation onto the Push.

## Files

| File | Role |
|---|---|
| `contract.py` | The MIDI agreement between the bridges and Traktor. Channels: Ch01–04 decks A–D, Ch05 global, Ch06 free pads, Ch07 user pads, Ch09–12 remix cells. **Single source of truth.** |
| `build_tsi.py` | Generates `Push2 Bridge.tsi` (≈1,120 mappings) from `contract.py`. Holds the Traktor command IDs. |
| `push_quad.py` | Four-deck layout: each 4×4 corner of the pads is a deck. Subclasses `Bridge`. Default for `install.sh`. |
| `push_bridge.py` | 8-column layout with CUES/STEMS/REMIX/USER modes and deck focus. Also holds `Palette`, `BeatClock` and the base `Bridge`. |
| `build_simple_tsi.py` | `Push2 Simple.tsi`: 2 decks, no script, plain on/off LEDs straight to the Push User Port. |
| `make_cheatsheet.py` | Draws `docs/cheatsheet.svg` for the four-deck layout. Re-run after layout changes. |
| `install.sh` / `uninstall.sh` | Venv in `~/Library/Application Support/Push2TraktorBridge`, LaunchAgent `local.push2-traktor-bridge`, `.tsi` files to the Desktop. |
| `tests/sim_quad.py` | Fake Push + fake Traktor over virtual MIDI ports; 21 checks of `push_quad.py`. No hardware needed. |

`*.tsi` files are build output and are gitignored: `build_tsi.py` copies the
MIDI address list (`DDDC`) from Traktor's bundled Reloop READY mapping, so it
needs Traktor installed and the output isn't redistributed.

## Commands

```bash
./install.sh                                   # install + start at login
python3 build_tsi.py                           # rebuild Push2 Bridge.tsi after editing contract.py
python3 make_cheatsheet.py                     # redraw docs/cheatsheet.svg
~/Library/Application\ Support/Push2TraktorBridge/venv/bin/python tests/sim_quad.py
launchctl bootout gui/$(id -u)/local.push2-traktor-bridge    # stop the login bridge
venv/bin/python push_quad.py --monitor         # run in the foreground, print Traktor's feedback
```

Run `tests/sim_quad.py` after any change to `push_quad.py`, `push_bridge.py` or `contract.py`.

## Changing the layout

1. Need a new Traktor command? Add an address to `contract.py`, add the mapping in
   `build_mappings()` in `build_tsi.py`, rebuild, and re-import the .tsi in Traktor
   (Controller Manager → delete the old device → Import TSI).
2. Pad behaviour lives in `pad()` / `button()` / `encoder()`; colours live in `frame()`.
   `frame()` returns `{("note"|"cc", number): palette index}` and `render()` sends only
   the changes.
3. Update `make_cheatsheet.py`, the README and the tests.

## Traktor .tsi format (reverse-engineered, Traktor 4.4.2)

- XML wrapper; the `DeviceIO.Config.Controller` entry holds a base64 blob of frames:
  4-char tag + big-endian uint32 size. `DIOM > DIOI, DEVS > DEVI("Generic MIDI") > DDAT >
  DDIF, DDIV, DDIC (name), DDPT (in/out port), DDDC (address lists), DDCB > CMAS > CMAI > CMAD, DCBM, DVST`.
- `CMAI` = binding id, 0 in / 1 out, command id. `DCBM` maps binding id → `"Ch01.Note.C2"` / `"Ch01.CC.071"`
  (note 36 = C2).
- `CMAD` = 12 int header (version 4, control type 0 button / 1 fader / 2 encoder / 0xFFFF LED,
  interaction 0 trigger / 1 toggle / 2 hold / 3 direct / 4 relative / 5 inc / 6 dec / 8 output,
  assignment (deck/unit, -1 device target; stem slot = deck*4+slot), …, sensitivity float, …,
  value) + comment + 17 int tail (modifier conditions, controller range, MIDI range, …).
  `Mapping.cmad()` in `build_tsi.py` is the reference implementation.
- Encoders: relative mode uses Traktor's default 7Fh/01h, which is what the Push sends.

## Push 2 facts used here

- User mode sysex `F0 00 21 1D 01 01 0A 01 F7`. Without it (or the User button) the Push
  ignores LED messages on the User Port. The bridges send it on connect.
- Palette entry: `F0 00 21 1D 01 01 03 idx r_lo r_hi g_lo g_hi b_lo b_hi w_lo w_hi F7`,
  then `… 05 F7` to apply. `Palette` loads 12 colours × full/mid/dim into indices 1–36.
- Pads: notes 36–99, bottom-left first. Encoders CC 71–78 (touch = notes 0–7), master CC 79.
  Buttons: above screen CC 102–109, below CC 20–27, Shift CC 49. White-only buttons: 16 dim, 127 full.

## Gotchas

- Traktor writes the macOS port as `Ableton Push 2 (User Port)` (with brackets); mido shows
  `Ableton Push 2 User Port`.
- Only one bridge can own the "Push2 Traktor Bridge" port; the installer runs one layout at a time.
- Never edit `Traktor Settings.tsi` while Traktor is running; it overwrites it on quit.
- Hardware feedback from Traktor directly to the Push User Port (the simple .tsi) has not
  been confirmed to light the pads; the bridge path is the supported one.
