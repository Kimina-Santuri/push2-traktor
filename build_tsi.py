"""Generate "Push2 Bridge.tsi" for Traktor Pro 4 from contract.py.

Traktor's .tsi is undocumented. The layout used here was decoded from the
mappings that ship with Traktor 4.4.2, and the command IDs were read from
the Traktor binary. The MIDI port list (every CC/note on 16 channels) is
copied from one of those shipped mappings, so Traktor must be installed.

    python3 build_tsi.py            -> writes "Push2 Bridge.tsi" next to this file
"""
import base64
import glob
import os
import re
import struct
import sys

import contract as K

PORT_NAME = "Push2 Traktor Bridge"
HERE = os.path.dirname(os.path.abspath(__file__))
REFERENCE_GLOB = os.path.expanduser(
    "~/Documents/Native Instruments/Traktor */Settings/Default Settings/Controller/Reloop/*READY.tsi")

# Traktor command IDs (from the Traktor Pro 4.4.2 binary)
PLAY, CUE, CUP, SYNC, MASTER, KEYLOCK, FLUX, CENSOR = 100, 206, 204, 125, 2293, 400, 2350, 874
HOTCUE, HOTCUE_DEL, HOTCUE_TYPE1 = 2328, 2331, 2333
LOOP_SET, LOOP_SIZE_SEL, LOOP_ACTIVE, LOOP_IN, LOOP_OUT, IN_LOOP = 2317, 2196, 202, 2392, 2393, 203
MOVE, MOVE_SIZE, MOVE_MODE = 2351, 2372, 2391
CUE_JUMP, CUE_STORE, CUE_DEL_CUR = 2306, 2308, 2309
FX_UNIT1_ON, FX_UNIT2_ON = 321, 322
LOAD_TRACK, LOAD_STEMS = 3076, 3087
FILTER_ON, FILTER = 319, 320
SLOT_MUTE, SLOT_FX, SLOT_STOP, SLOT_STATE = 259, 239, 236, 247
SLOT_VOL, SLOT_FILTER, SLOT_FILTER_ON = 251, 249, 250
REMIX_PAGE = 733
CELL_TRIGGER1, CELL_STATE1 = 601, 665
DECK_FLAVOR, TRACK_END, BEAT_PHASE, DECK_LOADED = 2302, 520, 513, 2591
UNIT_ON, UNIT_KNOB1, UNIT_BUTTON1, UNIT_DRYWET = 369, 366, 370, 365
BROWSE_LIST, BROWSE_TREE, TREE_EXPAND, BROWSER_VIEW = 3200, 3328, 3329, 4209
FOCUS, SEND_STATE = 9, 3048
JOG_TURN, JOG_TOUCH = 120, 2187

# control types / interaction modes as stored in the file
BUTTON, FADER, ENCODER, LED = 0, 1, 2, 0xFFFF
TRIGGER, TOGGLE, HOLD, DIRECT, RELATIVE, INC, DEC, OUTPUT = 0, 1, 2, 3, 4, 5, 6, 8


def fbits(x):
    return struct.unpack(">i", struct.pack(">f", x))[0]


def wstr(s):
    return struct.pack(">I", len(s)) + s.encode("utf-16-be")


def frame(tag, payload):
    return tag.encode() + struct.pack(">I", len(payload)) + payload


def note_name(ch, n):
    names = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
    return "Ch%02d.Note.%s%d" % (ch + 1, names[n % 12], n // 12 - 1)


def cc_name(ch, n):
    return "Ch%02d.CC.%03d" % (ch + 1, n)


class Mapping:
    def __init__(self, midi, out, cmd, ctl, mode, asg=0, value=None, rng=(0, 1),
                 midi_rng=(0, 127), floats=False, comment="", sens=5.0):
        self.__dict__.update(locals())

    def cmad(self):
        has_val = self.value is not None
        vtype = 2 if self.floats else 1
        val = (fbits(self.value) if self.floats else self.value) if has_val else 0
        head = struct.pack(">4i3i", 4, self.ctl, self.mode, self.asg, 0, 0, 0)
        head += struct.pack(">2i3i", fbits(self.sens), 0, int(has_val), vtype, val)
        lo, hi = self.rng
        if self.floats:
            rng = [2, fbits(lo), 2, fbits(hi)]
            res = [1, 2, fbits(0.0625)]
        else:
            rng = [1, lo, 1, hi]
            # Second field is "Blend" on an output: off, Traktor sends only MIDI max/min for "value in range or not",
            # so a numeric output (hotcue type, deck flavor, loop size...) needs it on to send the value itself.
            blend = self.mode == OUTPUT and tuple(self.rng) != (0, 1)
            res = [int(has_val or blend or self.mode in (INC, DEC, RELATIVE)), 1, 1]
        tail = [0, 0, 0, 0, 0, 0] + rng + list(self.midi_rng) + [0] + res + [0]
        return head + wstr(self.comment) + struct.pack(">%di" % len(tail), *tail)


def build_mappings():
    M = []

    def btn(ch, n, cmd, mode, asg, comment, value=None, rng=(0, 1), out=True):
        M.append(Mapping(note_name(ch, n), False, cmd, BUTTON, mode, asg, value, rng, comment=comment))
        if out:
            M.append(Mapping(note_name(ch, n), True, cmd, LED, OUTPUT, asg, comment=comment + " LED"))

    def led(ch, n, cmd, asg, comment, rng=(0, 1), midi_rng=(0, 127), floats=False):
        M.append(Mapping(note_name(ch, n), True, cmd, LED, OUTPUT, asg, None, rng, midi_rng,
                         floats, comment))

    def fader(ch, cc, cmd, asg, comment):
        M.append(Mapping(cc_name(ch, cc), False, cmd, FADER, DIRECT, asg, rng=(0.0, 1.0),
                         floats=True, comment=comment))
        M.append(Mapping(cc_name(ch, cc), True, cmd, LED, OUTPUT, asg, rng=(0.0, 1.0),
                         floats=True, comment=comment + " feedback"))

    for d, ch in enumerate(K.DECK_CH):
        D = "ABCD"[d]
        for i in range(8):
            btn(ch, K.HOTCUE[i], HOTCUE, HOLD, d, "%s Hotcue %d" % (D, i + 1), i, (-1, 7), out=False)
            led(ch, K.HOTCUE[i], HOTCUE_TYPE1 + i, d, "%s Hotcue %d type+1" % (D, i + 1),
                rng=(-1, 6), midi_rng=(0, 7))
            btn(ch, K.HOTCUE_DELETE[i], HOTCUE_DEL, DIRECT, d, "%s Delete hotcue %d" % (D, i + 1),
                i, (-1, 7), out=False)
        btn(ch, K.PLAY, PLAY, TOGGLE, d, D + " Play/Pause")
        btn(ch, K.CUE, CUE, HOLD, d, D + " Cue")
        btn(ch, K.CUP, CUP, HOLD, d, D + " CUP", out=False)
        btn(ch, K.SYNC, SYNC, TOGGLE, d, D + " Sync")
        btn(ch, K.MASTER, MASTER, TRIGGER, d, D + " Tempo master")
        btn(ch, K.KEYLOCK, KEYLOCK, TOGGLE, d, D + " Keylock")
        btn(ch, K.FLUX, FLUX, TOGGLE, d, D + " Flux")
        btn(ch, K.CENSOR, CENSOR, HOLD, d, D + " Censor", out=False)
        for n, idx in zip(K.LOOP_SIZE, K.LOOP_SIZE_INDEX):
            btn(ch, n, LOOP_SET, DIRECT, d, "%s Loop set idx %d" % (D, idx), idx, (-1, 10), out=False)
        led(ch, K.LOOP_SIZE_NOW, LOOP_SIZE_SEL, d, D + " Loop size index", (0, 10), (0, 10))
        btn(ch, K.LOOP_ACTIVE, LOOP_ACTIVE, TOGGLE, d, D + " Loop active")
        btn(ch, K.LOOP_IN, LOOP_IN, TRIGGER, d, D + " Loop in", out=False)
        btn(ch, K.LOOP_OUT, LOOP_OUT, TRIGGER, d, D + " Loop out", out=False)
        led(ch, K.IN_LOOP, IN_LOOP, d, D + " In active loop")
        for n, beats in zip(K.BEATJUMP, K.BEATJUMP_BEATS):
            # same three-step recipe as Traktor's own DDJ-FLX4 mapping: mode, size, move
            size = {1: 6, 4: 8, 16: 10}[abs(beats)]
            c = "%s Beatjump %+d" % (D, beats)
            btn(ch, n, MOVE_MODE, DIRECT, d, c + " mode", 0, (0, 3), out=False)
            btn(ch, n, MOVE_SIZE, DIRECT, d, c + " size", size, (0, 12), out=False)
            btn(ch, n, MOVE, INC if beats > 0 else DEC, d, c, None, (-1, 1), out=False)
        btn(ch, K.CUE_PREV, CUE_JUMP, DEC, d, D + " Prev cue", None, (-1, 1), out=False)
        btn(ch, K.CUE_NEXT, CUE_JUMP, INC, d, D + " Next cue", None, (-1, 1), out=False)
        btn(ch, K.CUE_STORE, CUE_STORE, TRIGGER, d, D + " Store floating cue", out=False)
        btn(ch, K.CUE_DELETE_CURRENT, CUE_DEL_CUR, TRIGGER, d, D + " Delete current hotcue", out=False)
        btn(ch, K.FX1_ASSIGN, FX_UNIT1_ON, TOGGLE, d, D + " FX unit 1 assign")
        btn(ch, K.FX2_ASSIGN, FX_UNIT2_ON, TOGGLE, d, D + " FX unit 2 assign")
        btn(ch, K.LOAD_TRACK, LOAD_TRACK, TRIGGER, d, D + " Load selected", out=False)
        btn(ch, K.LOAD_STEMS, LOAD_STEMS, TRIGGER, d, D + " Load as stems", out=False)
        btn(ch, K.FILTER_ON, FILTER_ON, TOGGLE, d, D + " Filter on")
        fader(ch, K.DECK_FILTER_CC, FILTER, d, D + " Filter")
        M.append(Mapping(cc_name(ch, K.JOG_CC), False, JOG_TURN, ENCODER, RELATIVE, d,
                         rng=(-16.0, 16.0), floats=True, comment=D + " Jog", sens=1.5))
        M.append(Mapping(note_name(ch, K.JOG_TOUCH), False, JOG_TOUCH, BUTTON, HOLD, d,
                         comment=D + " Jog touch (scratch)"))
        led(ch, K.DECK_FLAVOR, DECK_FLAVOR, d, D + " Deck flavor", (0, 3), (0, 3))
        led(ch, K.TRACK_END, TRACK_END, d, D + " Track end warning")
        led(ch, K.BEAT_PHASE, BEAT_PHASE, d, D + " Beat phase", (-0.5, 0.5), floats=True)
        led(ch, K.DECK_LOADED, DECK_LOADED, d, D + " Deck loaded")
        btn(ch, K.REMIX_PAGE_DOWN, REMIX_PAGE, DEC, d, D + " Remix page -", None, (0, 3), out=False)
        btn(ch, K.REMIX_PAGE_UP, REMIX_PAGE, INC, d, D + " Remix page +", None, (0, 3), out=False)
        led(ch, K.REMIX_PAGE, REMIX_PAGE, d, D + " Remix page", (0, 3), (0, 3))
        for s in range(4):
            slot = d * 4 + s
            c = "%s Slot %d" % (D, s + 1)
            btn(ch, K.SLOT_MUTE[s], SLOT_MUTE, TOGGLE, slot, c + " mute")
            btn(ch, K.SLOT_FX[s], SLOT_FX, TOGGLE, slot, c + " FX send")
            btn(ch, K.SLOT_STOP[s], SLOT_STOP, TRIGGER, slot, c + " stop", out=False)
            btn(ch, K.SLOT_FILTER_ON[s], SLOT_FILTER_ON, TOGGLE, slot, c + " filter on")
            led(ch, K.SLOT_STATE[s], SLOT_STATE, slot, c + " state", (0, 4), (0, 4))
            fader(ch, K.SLOT_VOLUME_CC[s], SLOT_VOL, slot, c + " volume")
            fader(ch, K.SLOT_FILTER_CC[s], SLOT_FILTER, slot, c + " filter")
            for cell in range(16):
                n = K.cell_note(s, cell)
                M.append(Mapping(note_name(K.CELL_CH[d], n), False, CELL_TRIGGER1 + s * 16 + cell,
                                 BUTTON, HOLD, d, comment="%s cell %d" % (c, cell + 1)))
                M.append(Mapping(note_name(K.CELL_CH[d], n), True, CELL_STATE1 + s * 16 + cell,
                                 LED, OUTPUT, d, None, (0, 3), (0, 3),
                                 comment="%s cell %d state" % (c, cell + 1)))

    g = K.GLOBAL_CH
    for u in range(2):
        btn(g, K.FX_ON[u], UNIT_ON, TOGGLE, u, "FX%d on" % (u + 1))
        for b in range(3):
            btn(g, K.FX_BUTTON[u][b], UNIT_BUTTON1 + b, TOGGLE, u, "FX%d button %d" % (u + 1, b + 1))
            fader(g, K.FX_KNOB_CC[u][b], UNIT_KNOB1 + b, u, "FX%d knob %d" % (u + 1, b + 1))
        fader(g, K.FX_DRYWET_CC[u], UNIT_DRYWET, u, "FX%d dry/wet" % (u + 1))
    btn(g, K.BROWSE_UP, BROWSE_LIST, DEC, 0, "Browser up", None, (-128, 128), out=False)
    btn(g, K.BROWSE_DOWN, BROWSE_LIST, INC, 0, "Browser down", None, (-128, 128), out=False)
    btn(g, K.TREE_UP, BROWSE_TREE, DEC, 0, "Tree up", None, (-128, 128), out=False)
    btn(g, K.TREE_DOWN, BROWSE_TREE, INC, 0, "Tree down", None, (-128, 128), out=False)
    btn(g, K.TREE_EXPAND, TREE_EXPAND, DIRECT, 0, "Tree expand/collapse", 1, (0, 1), out=False)
    btn(g, K.BROWSER_VIEW, BROWSER_VIEW, TOGGLE, 0, "Browser view")
    btn(g, K.SEND_STATE, SEND_STATE, TRIGGER, 0, "Send monitor state", out=False)
    for d in range(4):
        btn(g, K.FOCUS[d], FOCUS, DIRECT, 0, "Focus deck " + "ABCD"[d], d, (0, 3), out=False)
    led(g, K.FOCUS_NOW, FOCUS, 0, "Focused deck", (0, 3), (0, 3))
    return M


def load_reference():
    paths = sorted(glob.glob(REFERENCE_GLOB))
    if not paths:
        sys.exit("Could not find Traktor's bundled Reloop READY mapping (needed for the MIDI port list).")
    xml = open(paths[-1], "rb").read().decode("utf-8")
    blob = base64.b64decode(re.search(r'Controller" Type="3" Value="([^"]+)"', xml).group(1))
    # pull the first device's DDIV, DDDC (all MIDI addresses) and DVST frames verbatim
    keep = {}
    for tag in ("DDIV", "DDDC", "DVST"):
        i = blob.index(tag.encode())
        size = struct.unpack(">I", blob[i + 4:i + 8])[0]
        keep[tag] = blob[i:i + 8 + size]
    return keep


def build_tsi(mappings):
    ref = load_reference()
    # One binding per mapping, even when several share a MIDI address (a pad's press and its LED, the three
    # steps of a beatjump). Traktor keeps only the first mapping of a shared binding and drops the rest.
    cmai = b"".join(
        frame("CMAI", struct.pack(">3I", i + 1, int(m.out), m.cmd) + frame("CMAD", m.cmad()))
        for i, m in enumerate(mappings))
    cmas = frame("CMAS", struct.pack(">I", len(mappings)) + cmai)
    dcbm = frame("DCBM", struct.pack(">I", len(mappings)) + b"".join(
        frame("DCBM", struct.pack(">I", i + 1) + wstr(m.midi)) for i, m in enumerate(mappings)))
    ddat = (frame("DDIF", struct.pack(">I", 0))          # device target: Focus
            + ref["DDIV"]
            + frame("DDIC", wstr("Push 2 Bridge (smart LEDs)"))
            + frame("DDPT", wstr(PORT_NAME) + wstr(PORT_NAME))
            + ref["DDDC"]
            + frame("DDCB", cmas + dcbm)
            + ref["DVST"])
    devi = frame("DEVI", wstr("Generic MIDI") + frame("DDAT", ddat))
    diom = frame("DIOM", frame("DIOI", struct.pack(">I", 1)) + frame("DEVS", struct.pack(">I", 1) + devi))
    return ('<?xml version="1.0" encoding="UTF-8" standalone="no" ?>\n'
            '<NIXML><TraktorSettings><Entry Name="DeviceIO.Config.Controller" Type="3" Value="%s"></Entry>\n'
            '<Entry Name="Flavour" Type="1" Value="1"></Entry>\n'
            '<Entry Name="Version" Type="1" Value="3"></Entry>\n'
            '</TraktorSettings>\n</NIXML>' % base64.b64encode(diom).decode())


if __name__ == "__main__":
    maps = build_mappings()
    out = os.path.join(HERE, "Push2 Bridge.tsi")
    open(out, "w").write(build_tsi(maps))
    print("wrote %s (%d mappings)" % (out, len(maps)))
