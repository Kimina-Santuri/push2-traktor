"""Generate "Push2 Simple.tsi": Push 2 straight into Traktor, no bridge script.

Press the Push's User button, import the file, set In/Out port to
"Ableton Push 2 User Port". Left half of the pads = Deck A, right half = Deck B.

    python3 build_simple_tsi.py     -> writes "Push2 Simple.tsi" next to this file
"""
import base64
import os
import struct

from build_tsi import fbits, frame, wstr, note_name, cc_name, load_reference

PORT = "Ableton Push 2 (User Port)"     # Traktor's spelling of the macOS port name
HERE = os.path.dirname(os.path.abspath(__file__))

# Push 2 default palette (User mode): velocity picks the colour
OFF, GREY, WHITE, BLUE, GREEN, RED = 0, 124, 122, 125, 126, 127

BUTTON, ENCODER, LED = 0, 2, 0xFFFF
TRIGGER, TOGGLE, HOLD, DIRECT, RELATIVE, OUTPUT = 0, 1, 2, 3, 4, 8
SHIFT_MOD = 2548                     # Traktor "Modifier #1"


def cmad(ctl, mode, asg, value=None, floats=False, rng=(0, 1), midi_rng=(0, 127),
         sens=5.0, cond=None, comment=""):
    has_val = value is not None
    val = (fbits(value) if floats else value) if has_val else 0
    head = struct.pack(">7i", 4, ctl, mode, asg, 0, 0, 0)
    head += struct.pack(">5i", fbits(sens), 0, int(has_val), 2 if floats else 1, val)
    m = [SHIFT_MOD, 0, cond] if cond is not None else [0, 0, 0]
    lo, hi = rng
    if floats:
        tail = m + [0, 0, 0, 2, fbits(lo), 2, fbits(hi)] + list(midi_rng) + [0, 1, 2, fbits(0.0625), 0]
    else:
        flag = int(has_val or cond is not None or mode == RELATIVE)
        tail = m + [0, 0, 0, 1, lo, 1, hi] + list(midi_rng) + [0, flag, 1, 1, 0]
    return head + wstr(comment) + struct.pack(">17i", *tail)


def pad(row, col):
    return note_name(0, 36 + row * 8 + col)


def build():
    M = []   # (midi name, is_output, command id, CMAD bytes)

    def add(midi, cmd, *a, out=False, **kw):
        M.append((midi, out, cmd, cmad(*a, **kw)))

    def led(midi, cmd, asg, on, off=GREY, rng=(0, 1), comment=""):
        add(midi, cmd, LED, OUTPUT, asg, rng=rng, midi_rng=(off, on), out=True, comment=comment)

    add(cc_name(0, 49), SHIFT_MOD, BUTTON, HOLD, 0, value=1, rng=(0, 7), comment="Shift")
    # Shift is a white-only button: 16 = dim, 127 = full
    led(cc_name(0, 49), SHIFT_MOD, 0, 127, off=16, comment="Shift LED")

    for deck in (0, 1):
        D = "AB"[deck]
        c0 = deck * 4                                    # first pad column of this deck
        # bottom row: Play, Cue, Sync, Load
        for col, (cmd, mode, colour, name) in enumerate([
                (100, TOGGLE, GREEN, "Play/Pause"), (206, HOLD, RED, "Cue"),
                (125, TOGGLE, WHITE, "Sync"), (3086, TRIGGER, None, "Load selected")]):
            add(pad(0, c0 + col), cmd, BUTTON, mode, deck, comment="%s %s" % (D, name))
            if colour:
                led(pad(0, c0 + col), cmd, deck, colour, comment="%s %s LED" % (D, name))
            else:
                add(pad(0, c0 + col), 2591, LED, OUTPUT, deck, midi_rng=(GREY, WHITE), out=True,
                    comment=D + " Deck loaded LED")
        # rows 1-2: hotcues 1-8 (Shift + pad deletes)
        for i in range(8):
            midi = pad(2 - i // 4, c0 + i % 4)
            add(midi, 2328, BUTTON, HOLD, deck, value=i, rng=(-1, 7), cond=0,
                comment="%s Hotcue %d" % (D, i + 1))
            add(midi, 2331, BUTTON, DIRECT, deck, value=i, rng=(-1, 7), cond=1,
                comment="%s Delete hotcue %d (Shift)" % (D, i + 1))
            led(midi, 2333 + i, deck, BLUE, rng=(-1, 0), comment="%s Hotcue %d LED" % (D, i + 1))
        # deck button for effects: send this deck to its FX unit
        fx_assign = 321 + deck                             # "FX Unit 1 On" / "FX Unit 2 On"
        add(pad(3, c0), fx_assign, BUTTON, TOGGLE, deck, comment="%s to FX unit %d" % (D, deck + 1))
        led(pad(3, c0), fx_assign, deck, BLUE, comment="%s FX assign LED" % D)

        # jog: outer encoders (1 for A, 8 for B); touching the knob = scratch, turning alone = nudge
        enc = 0 if deck == 0 else 7
        add(cc_name(0, 71 + enc), 120, ENCODER, RELATIVE, deck, floats=True, rng=(-16.0, 16.0),
            sens=1.5, comment=D + " Jog")
        add(note_name(0, enc), 2187, BUTTON, HOLD, deck, comment=D + " Jog touch (scratch)")

        # FX unit for this deck: dry/wet, knob 1, knob 2 on the encoders next to the jog
        encs = [1, 2, 3] if deck == 0 else [6, 5, 4]
        for e, cmd, name in zip(encs, (365, 366, 367), ("Dry/Wet", "Knob 1", "Knob 2")):
            add(cc_name(0, 71 + e), cmd, ENCODER, RELATIVE, deck, floats=True, rng=(0.0, 1.0),
                sens=2.0, comment="FX%d %s" % (deck + 1, name))
        # buttons above the screen: FX unit on + buttons 1-3
        for b, cmd in enumerate((369, 370, 371, 372)):
            midi = cc_name(0, 102 + deck * 4 + b)
            add(midi, cmd, BUTTON, TOGGLE, deck, comment="FX%d %s" % (deck + 1, ["On", "B1", "B2", "B3"][b]))
            led(midi, cmd, deck, GREEN, comment="FX%d LED %d" % (deck + 1, b))
        # buttons below the screen: Loop on, Keylock, Master, Flux (lit when active)
        for b, (cmd, colour, name) in enumerate([
                (202, GREEN, "Loop on"), (400, BLUE, "Keylock"),
                (2293, WHITE, "Master"), (2350, RED, "Flux")]):
            midi = cc_name(0, 20 + deck * 4 + b)
            add(midi, cmd, BUTTON, TOGGLE, deck, comment="%s %s" % (D, name))
            led(midi, cmd, deck, colour, comment="%s %s LED" % (D, name))

    # master encoder = browse the track list
    add(cc_name(0, 79), 3200, ENCODER, RELATIVE, 0, rng=(-128, 128), comment="Browse list")
    return M


def build_tsi(mappings):
    ref = load_reference()
    names = []
    for m in mappings:
        if m[0] not in names:
            names.append(m[0])
    bid = {n: i + 1 for i, n in enumerate(names)}
    cmai = b"".join(frame("CMAI", struct.pack(">3I", bid[n], int(o), c) + frame("CMAD", d))
                    for n, o, c, d in mappings)
    cmas = frame("CMAS", struct.pack(">I", len(mappings)) + cmai)
    dcbm = frame("DCBM", struct.pack(">I", len(names)) + b"".join(
        frame("DCBM", struct.pack(">I", bid[n]) + wstr(n)) for n in names))
    ddat = (frame("DDIF", struct.pack(">I", 0)) + ref["DDIV"]
            + frame("DDIC", wstr("Push 2 Simple (2 decks)"))
            + frame("DDPT", wstr(PORT) + wstr(PORT)) + ref["DDDC"]
            + frame("DDCB", cmas + dcbm) + ref["DVST"])
    devi = frame("DEVI", wstr("Generic MIDI") + frame("DDAT", ddat))
    diom = frame("DIOM", frame("DIOI", struct.pack(">I", 1)) + frame("DEVS", struct.pack(">I", 1) + devi))
    return ('<?xml version="1.0" encoding="UTF-8" standalone="no" ?>\n'
            '<NIXML><TraktorSettings><Entry Name="DeviceIO.Config.Controller" Type="3" Value="%s"></Entry>\n'
            '<Entry Name="Flavour" Type="1" Value="1"></Entry>\n'
            '<Entry Name="Version" Type="1" Value="3"></Entry>\n'
            '</TraktorSettings>\n</NIXML>' % base64.b64encode(diom).decode())


if __name__ == "__main__":
    maps = build()
    out = os.path.join(HERE, "Push2 Simple.tsi")
    open(out, "w").write(build_tsi(maps))
    print("wrote %s (%d mappings)" % (out, len(maps)))
