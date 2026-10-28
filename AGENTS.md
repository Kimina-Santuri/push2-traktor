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
| `push_display.py` | The Push 2 screen over USB (pyusb + libusb): `render(view)` draws 960×160 with Pillow, `encode()` makes the frame, `Screen` thread sends ~16 fps and reconnects. `QuadBridge.display_view()` builds the view. |
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
  (note 36 = C2). **Every CMAI needs its own binding id**, even on a shared MIDI address: Traktor keeps only the
  first mapping of a shared binding and silently drops the rest.
- Output (LED) CMAD tail: controller range, MIDI range, invert, **blend**. With blend off, Traktor sends MIDI max while
  the value is inside the controller range and min otherwise; numeric outputs (hotcue type, deck flavor, loop size)
  need blend on. Deck flavor values: 0 track, 1 remix, 2 stem, 3 live input.
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

## 2026-10-27: pads dim / white on USB power

- User report: the pads light but show no colour, or are just dim, and look white in shade. The Push was running on
  USB power only (no adapter).
- Checked: Traktor's saved settings have "Push 2 Bridge (smart LEDs)" on ports Push2 Traktor Bridge. The installed
  bridge matched the repo. The palette sysex matches the Push 2 layout (`03 idx` + r/g/b/w as 7-bit lsb, msb, then
  `05` to apply). The log shows the Push reconnecting several times.
- Changed: `QuadBridge.setup()` sends User mode, palette and LED brightness, and is resent 1.5 s and 5 s after every
  connect, because a Push that is still starting up can miss the palette and stay on its built-in colours.
  `Palette.sysex()` now ends with `06 127` (LED brightness: full), which also affects push_bridge.py.
  sim_quad.py: 21/21 pass. Installed to `~/Library/Application Support/Push2TraktorBridge` and restarted.
- NOT verified: on hardware with the power adapter. On USB power alone the Push 2 limits its LED brightness itself;
  "dim" (8 %) pads may then be close to invisible.

## 2026-10-28: mapping fixes found with --monitor on real hardware

- **Shared bindings were dropped.** build_tsi gave mappings on the same MIDI address one binding id. Traktor 4.4.2
  keeps only the first CMAI per binding (its saved copy had 644 of 1121, with 45 of 474 outputs), so the pad LEDs,
  Play/Cue/Sync LEDs and beatjump size/move steps were lost. Fix: one binding (and DCBM entry) per mapping, in
  build_tsi.py and build_simple_tsi.py. (Factory .tsi files seem to share ids only because they hold several devices.)
- **Numeric outputs need Blend.** CMAD tail field 13 on an output is Blend. With it off, Traktor sends MIDI max when the
  value is inside the controller range and min otherwise. So every hotcue read 7 and deck flavor read 3, and the
  bridge drew white. Fix: Blend on for outputs whose range isn't (0, 1). Float outputs already had it.
- **Deck flavor is 0 track, 1 remix, 2 stem, 3 live** (was assumed 1 = stem). `K.FLAVOR_STEM/FLAVOR_REMIX`.
- **User's layout requests (push_quad.py):** a stem pad is solid in its colour while playing and off when muted or on a non-stem
  deck. Hotcues are solid once set. Loops are solid: selected size mid, full while looping. Play still pulses (user happy). README and
  cheat sheet updated. sim_quad 21/21. The user re-imported the rebuilt Push2 Bridge.tsi (copied to the Desktop) and
  confirmed hotcues, Play, Sync and loops respond, then confirmed the solid stem/hotcue/loop layout ("perfect").
  Still on USB power only (colours dim). Installer prints a re-import note; README has an Updating section.
  Committed and pushed to GitHub 2026-10-28.

## 2026-10-28: the Push 2 screen

- User asked for the screen with everything proposed. Track titles aren't possible: Traktor sends no text over MIDI
  (the Broadcasting/Icecast route was mentioned but not built).
- `push_display.py`: frame = 16-byte header FF CC AA 88 + 160 lines of 2048 bytes (960 px BGR565 LE, red in the low bits, + 128
  filler), XOR E7 F3 E7 FF; bulk endpoint 0x01 on interface 0 of 2982:1967. Must be sent continuously (blank after 2 s).
  **The header must be its own 16-byte transfer and the pixels go in 16 KB transfers**: one long transfer
  (header + pixels) was accepted without error but the screen stayed black. It works on USB power alone.
- Data: BPM is measured from the beat-phase clock (60 / period, only while beats are fresh). The play position is a new output:
  Traktor command 103 "Seek Position" as float 0-1 on per-deck CC 10 (`K.SEEK_POS_CC`); the user must re-import the tsi
  (1125 mappings now). Everything else comes from state the bridge already had.
- Command ids can be looked up in CMDR's `cmdr.TsiLib/Commands/Interpretation/KnownCommands.cs` (TakTraum/cmdr on
  GitHub); it agrees with every id here (100, 513, 2302, 2591, 3048...). Useful ones not used yet: 64 master tempo
  (40-300 BPM), 123 tempo adjust (-1..1), 19 tempo range (enum 2 %...100 %), 402 key adjust.
- Installer: installs libusb with Homebrew if missing, copies push_display.py; requirements now include pyusb,
  Pillow, numpy. sim_quad runs the bridge with no_screen=True so the test never grabs a real display.
- Verified by the user 2026-10-28 after re-importing the tsi: "it looks really good and responds really well".
  Committed and pushed.
