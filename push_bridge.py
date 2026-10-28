"""Push 2 (or Push 1) <-> Traktor bridge with beat-synced, state-aware LEDs.

    pip install mido python-rtmidi
    python3 push_bridge.py              # run
    python3 push_bridge.py --monitor    # also print everything Traktor sends

It opens a virtual MIDI port called "Push2 Traktor Bridge" that the
generated "Push2 Bridge.tsi" talks to. Quit Ableton Live first.
"""
import argparse
import threading
import time

import mido

import contract as K

PORT_NAME = "Push2 Traktor Bridge"

# ---------------------------------------------------------------- Push I/O
PAD0 = 36                          # bottom-left pad; rows go up in steps of 8
CC_PLAY, CC_REC, CC_SHIFT, CC_MUTE, CC_STOP = 85, 86, 49, 60, 29
CC_PAGE_L, CC_PAGE_R, CC_BROWSE = 62, 63, 111
CC_LOWER = list(range(20, 28))     # row under the display: 4 modes, 4 decks
CC_UPPER = list(range(102, 110))   # row above the display: FX units
CC_ENC = list(range(71, 79))
CC_MASTER_ENC = 79
SYSEX_HDR = [0x00, 0x21, 0x1D, 0x01, 0x01]

MODES = ["CUES", "STEMS", "REMIX", "USER"]

# name -> RGB. Each colour gets three palette slots: full, mid, dim.
COLORS = {
    "red": (255, 0, 0), "orange": (255, 80, 0), "yellow": (255, 200, 0),
    "lime": (140, 255, 0), "green": (0, 255, 40), "teal": (0, 255, 160),
    "cyan": (0, 200, 255), "blue": (0, 60, 255), "purple": (140, 0, 255),
    "magenta": (255, 0, 200), "pink": (255, 70, 120), "white": (255, 255, 255),
}
LEVELS = {"full": 1.0, "mid": 0.35, "dim": 0.08}
# Push 1 has a fixed palette; these are the nearest entries
PUSH1 = {"red": 5, "orange": 9, "yellow": 13, "lime": 17, "green": 21, "teal": 29,
         "cyan": 33, "blue": 45, "purple": 49, "magenta": 53, "pink": 57, "white": 3}

DECK_COLORS = ["cyan", "orange", "purple", "lime"]
STEM_COLORS = ["orange", "yellow", "cyan", "magenta"]       # drums, bass, other, vocals
SLOT_COLORS = ["red", "yellow", "green", "blue"]
FX_COLORS = ["teal", "pink"]
# hotcue type + 1: 1 cue, 2 fade-in, 3 fade-out, 4 load, 5 grid, 6 loop
HOTCUE_COLORS = {1: "blue", 2: "yellow", 3: "orange", 4: "lime", 5: "white", 6: "green"}
LOOP_COLORS = ["red", "orange", "yellow", "lime", "green", "teal", "cyan", "blue"]


class Palette:
    def __init__(self, push1):
        self.push1 = push1
        self.index = {}
        i = 1
        for name in COLORS:
            for level in LEVELS:
                self.index[(name, level)] = i
                i += 1

    def sysex(self):
        """Messages that load our colours into the Push 2 palette."""
        msgs = []
        for (name, level), idx in self.index.items():
            r, g, b = (int(c * LEVELS[level]) for c in COLORS[name])
            w = max(r, g, b) if name == "white" else 0
            data = [0x03, idx]
            for c in (r, g, b, w):
                data += [c & 0x7F, c >> 7]
            msgs.append(mido.Message("sysex", data=SYSEX_HDR + data))
        msgs.append(mido.Message("sysex", data=SYSEX_HDR + [0x05]))   # reapply palette
        msgs.append(mido.Message("sysex", data=SYSEX_HDR + [0x06, 127]))   # LED brightness: full
        return msgs

    def __call__(self, name, level="full"):
        if not name:
            return 0
        if self.push1:
            base = PUSH1[name]
            return {"full": base, "mid": base + 1, "dim": base + 2}[level]
        return self.index[(name, level)]


# ---------------------------------------------------------------- beat clock
class BeatClock:
    """Turns Traktor's per-deck beat-phase sawtooth into beat ticks and a 0-1 phase."""

    def __init__(self):
        self.last = None
        self.last_beat = 0.0
        self.period = 0.5
        self.count = 0

    def feed(self, value, now):
        if self.last is not None and self.last - value > 40:      # wrapped = new beat
            gap = now - self.last_beat
            if 0.2 < gap < 2.0:
                self.period = 0.7 * self.period + 0.3 * gap
            self.last_beat = now
            self.count += 1
        self.last = value

    def phase(self, now):
        if now - self.last_beat > 2.0:                             # stale: free-run at 120
            return (now % 0.5) / 0.5, int(now / 0.5)
        p = (now - self.last_beat) / self.period
        return min(p, 0.999), self.count


# ---------------------------------------------------------------- bridge
class Bridge:
    def __init__(self, push_in, push_out, push1, monitor):
        self.push_in, self.push_out = push_in, push_out
        self.trak_in = mido.open_input(PORT_NAME, virtual=True)
        self.trak_out = mido.open_output(PORT_NAME, virtual=True)
        self.pal = Palette(push1)
        self.monitor = monitor
        self.state = {}               # (channel, kind, number) -> value from Traktor
        self.clocks = [BeatClock() for _ in range(4)]
        self.deck = 0
        self.mode = "CUES"
        self.shift = self.mute_held = self.stop_held = False
        self.pressed = set()          # pads held right now
        self.enc_value = {}           # (channel, cc) -> 0..127 float
        self.sent = {}                # what the Push currently shows
        self.lock = threading.Lock()

    # ---- helpers
    def get(self, ch, n, kind="note", default=0):
        return self.state.get((ch, kind, n), default)

    def to_traktor(self, kind, ch, n, value):
        if kind == "note":
            msg = mido.Message("note_on", channel=ch, note=n, velocity=value)
        else:
            msg = mido.Message("control_change", channel=ch, control=n, value=value)
        self.trak_out.send(msg)

    def tap(self, ch, n, down=True):
        self.to_traktor("note", ch, n, 127 if down else 0)

    def press(self, ch, n):
        self.tap(ch, n, True)
        self.tap(ch, n, False)

    # ---- Traktor -> bridge
    def on_traktor(self, msg):
        if msg.type not in ("note_on", "note_off", "control_change"):
            return
        kind = "cc" if msg.type == "control_change" else "note"
        n = msg.control if kind == "cc" else msg.note
        v = msg.value if kind == "cc" else (msg.velocity if msg.type == "note_on" else 0)
        with self.lock:
            self.state[(msg.channel, kind, n)] = v
            if kind == "cc":
                self.enc_value[(msg.channel, n)] = float(v)
            if kind == "note" and msg.channel in K.DECK_CH and n == K.BEAT_PHASE:
                self.clocks[msg.channel].feed(v, time.monotonic())
            if kind == "note" and msg.channel == K.GLOBAL_CH and n == K.FOCUS_NOW:
                self.deck = min(v, 3)
        if self.monitor and not (kind == "note" and n == K.BEAT_PHASE):
            print("traktor ch%02d %s %3d = %d" % (msg.channel + 1, kind, n, v))

    # ---- Push -> bridge
    def on_push(self, msg):
        with self.lock:
            if msg.type in ("note_on", "note_off") and PAD0 <= msg.note < PAD0 + 64:
                down = msg.type == "note_on" and msg.velocity > 0
                idx = msg.note - PAD0
                self.pad(idx // 8, idx % 8, down)
            elif msg.type == "control_change":
                self.button(msg.control, msg.value)
            elif msg.type == "pitchwheel":                     # touch strip -> deck filter
                d = K.DECK_CH[self.deck]
                if not self.get(d, K.FILTER_ON):
                    self.press(d, K.FILTER_ON)
                self.to_traktor("cc", d, K.DECK_FILTER_CC, (msg.pitch + 8192) * 127 // 16383)

    def pad(self, row, col, down):
        key = (row, col)
        (self.pressed.add if down else self.pressed.discard)(key)
        d = self.deck
        ch = K.DECK_CH[d]
        if self.mode == "USER":
            self.tap(K.USER_CH, PAD0 + row * 8 + col, down)
            return
        if self.mode == "CUES":
            if row == 7:
                if self.shift:
                    if down:
                        self.press(ch, K.HOTCUE_DELETE[col])
                else:
                    self.tap(ch, K.HOTCUE[col], down)
            elif row == 6:
                n = [K.CUE_PREV, K.CUE_NEXT, K.CUE_STORE, K.CUE_DELETE_CURRENT,
                     K.CUP, K.CENSOR, K.FLUX, K.KEYLOCK][col]
                if n in (K.CUP, K.CENSOR):
                    self.tap(ch, n, down)                       # hold-type commands
                elif down:
                    self.press(ch, n)
            elif row == 5 and down:
                n = [K.BEATJUMP[0], K.BEATJUMP[1], K.BEATJUMP[2], K.LOOP_IN,
                     K.LOOP_OUT, K.BEATJUMP[3], K.BEATJUMP[4], K.BEATJUMP[5]][col]
                self.press(ch, n)
            elif row == 4 and down:
                self.press(ch, K.LOOP_SIZE[col])
            elif row == 3 and down:
                n = [K.LOOP_ACTIVE, K.SYNC, K.MASTER, K.FX1_ASSIGN, K.FX2_ASSIGN,
                     K.FILTER_ON, K.LOAD_TRACK, K.LOAD_STEMS][col]
                self.press(ch, n)
            elif row in (1, 2):
                self.tap(K.FREE_CH, (row - 1) * 8 + col, down)
            return
        slot = col // 2
        if self.mode == "STEMS" and down:
            if row == 7:
                self.press(ch, K.SLOT_MUTE[slot])
            elif row == 6:
                self.press(ch, K.SLOT_FX[slot])
            else:                                               # rows 0-5 = volume steps
                self.to_traktor("cc", ch, K.SLOT_VOLUME_CC[slot], round((row + 1) * 127 / 6))
        elif self.mode == "REMIX":
            if self.mute_held or self.stop_held:
                if down and self.mute_held:
                    self.press(ch, K.SLOT_MUTE[slot])
                if down and self.stop_held and self.get(ch, K.SLOT_STATE[slot]) >= 2:
                    self.press(ch, K.SLOT_STOP[slot])           # only stop a playing slot
                return
            cell = (7 - row) * 2 + col % 2
            self.tap(K.CELL_CH[d], K.cell_note(slot, cell), down)

    def button(self, cc, value):
        down = value > 0
        d = K.DECK_CH[self.deck]
        if cc == CC_SHIFT:
            self.shift = down
        elif cc == CC_MUTE:
            self.mute_held = down
        elif cc == CC_STOP:
            self.stop_held = down
        elif cc == CC_PLAY and down:
            self.press(d, K.PLAY)
        elif cc == CC_REC:
            self.tap(d, K.CUE, down)
        elif cc in CC_LOWER[:4] and down:
            self.mode = MODES[cc - CC_LOWER[0]]
        elif cc in CC_LOWER[4:] and down:
            self.deck = cc - CC_LOWER[4]
            self.press(K.GLOBAL_CH, K.FOCUS[self.deck])
            flavor = self.get(K.DECK_CH[self.deck], K.DECK_FLAVOR)  # jump to the deck's natural mode
            if self.mode != "USER":
                self.mode = {K.FLAVOR_STEM: "STEMS", K.FLAVOR_REMIX: "REMIX"}.get(flavor, "CUES")
        elif cc in CC_UPPER and down:
            i = cc - CC_UPPER[0]
            unit, b = divmod(i, 4)
            self.press(K.GLOBAL_CH, K.FX_ON[unit] if b == 0 else K.FX_BUTTON[unit][b - 1])
        elif cc in (CC_PAGE_L, CC_PAGE_R) and down and self.mode == "REMIX":
            self.press(d, K.REMIX_PAGE_UP if cc == CC_PAGE_R else K.REMIX_PAGE_DOWN)
        elif cc == CC_BROWSE and down:
            self.press(d, K.LOAD_STEMS if self.shift else K.LOAD_TRACK)
        elif cc == CC_MASTER_ENC:
            up = value > 64
            if self.shift:
                self.press(K.GLOBAL_CH, K.TREE_UP if up else K.TREE_DOWN)
            else:
                self.press(K.GLOBAL_CH, K.BROWSE_UP if up else K.BROWSE_DOWN)
        elif cc in CC_ENC:
            self.encoder(cc - CC_ENC[0], value)

    def encoder(self, i, value):
        """Push encoders are relative; Traktor gets absolute values we keep in sync."""
        delta = value if value < 64 else value - 128
        if self.mode in ("STEMS", "REMIX"):
            ch = K.DECK_CH[self.deck]
            slot = i % 4
            cc = K.SLOT_VOLUME_CC[slot] if i < 4 else K.SLOT_FILTER_CC[slot]
            if i >= 4 and not self.get(ch, K.SLOT_FILTER_ON[slot]):
                self.press(ch, K.SLOT_FILTER_ON[slot])
        else:
            ch = K.GLOBAL_CH
            unit, k = divmod(i, 4)
            cc = K.FX_DRYWET_CC[unit] if k == 0 else K.FX_KNOB_CC[unit][k - 1]
        cur = self.enc_value.get((ch, cc), 64.0 if ch != K.GLOBAL_CH else 0.0)
        new = max(0.0, min(127.0, cur + delta * (0.25 if self.shift else 1.0)))
        self.enc_value[(ch, cc)] = new
        if int(new) != int(cur):
            self.to_traktor("cc", ch, cc, int(new))

    # ---- LEDs
    def frame(self, now):
        p = self.pal
        d = self.deck
        ch = K.DECK_CH[d]
        phase, beat = self.clocks[d].phase(now)
        pulse = "full" if phase < 0.25 else "mid"               # bright on the beat
        blink = phase < 0.5
        playing = self.get(ch, K.PLAY) > 0
        ending = self.get(ch, K.TRACK_END) > 0
        pads = {}

        if self.mode == "CUES":
            for c in range(8):
                t = self.get(ch, K.HOTCUE[c])
                pads[(7, c)] = p(HOTCUE_COLORS.get(t, "white"), "full" if t else "dim")
            row6 = ["white", "white", "green", "red", "yellow", "pink", "purple", "teal"]
            on6 = [None, None, None, None, None, None, self.get(ch, K.FLUX), self.get(ch, K.KEYLOCK)]
            for c, col in enumerate(row6):
                pads[(6, c)] = p(col, "full" if on6[c] else "mid" if on6[c] is not None else "dim")
            for c in range(8):
                jump = c not in (3, 4)
                pads[(5, c)] = p("cyan" if jump else "green", "mid" if jump else "dim")
            in_loop = self.get(ch, K.IN_LOOP) > 0
            size_now = self.get(ch, K.LOOP_SIZE_NOW, default=None)
            for c in range(8):
                current = size_now == K.LOOP_SIZE_INDEX[c]
                lvl = (pulse if in_loop else "full") if current else "dim"
                pads[(4, c)] = p(LOOP_COLORS[c], lvl)
            row3 = [(K.LOOP_ACTIVE, "green"), (K.SYNC, "blue"), (K.MASTER, "orange"),
                    (K.FX1_ASSIGN, FX_COLORS[0]), (K.FX2_ASSIGN, FX_COLORS[1]),
                    (K.FILTER_ON, "purple"), (None, "white"), (None, "magenta")]
            for c, (n, col) in enumerate(row3):
                on = n is not None and self.get(ch, n) > 0
                pads[(3, c)] = p(col, "full" if on else "dim")
            for r in (1, 2):
                for c in range(8):
                    on = self.get(K.FREE_CH, (r - 1) * 8 + c) > 0
                    pads[(r, c)] = p("white", "full" if on else "dim")
            for c in range(8):                                   # 2-bar beat counter
                lit = beat % 8 == c and playing
                color = "red" if ending else DECK_COLORS[d]
                pads[(0, c)] = p(color, "full" if lit else ("mid" if ending and blink else "dim"))

        elif self.mode == "STEMS":
            for s in range(4):
                color = STEM_COLORS[s]
                muted = self.get(ch, K.SLOT_MUTE[s]) > 0
                vol = self.enc_value.get((ch, K.SLOT_VOLUME_CC[s]), 127.0)
                level = vol / 127 * 6
                for c in (2 * s, 2 * s + 1):
                    pads[(7, c)] = p("red", pulse) if muted else p(color, "full")
                    pads[(6, c)] = p("white", "full" if self.get(ch, K.SLOT_FX[s]) else "dim")
                    for r in range(6):                           # VU-style volume bar
                        lit = r < round(level)
                        pads[(r, c)] = p(color, "dim" if muted else "full") if lit else 0

        elif self.mode == "REMIX":
            for s in range(4):
                for cell in range(16):
                    st = self.get(K.CELL_CH[d], K.cell_note(s, cell))
                    r, c = 7 - cell // 2, 2 * s + cell % 2
                    if st == 0:
                        v = 0
                    elif st == 2:
                        v = p(SLOT_COLORS[s], pulse)             # playing: breathes on the beat
                    elif st == 3:
                        v = p("white", "full") if blink else 0   # waiting for quantize
                    else:
                        v = p(SLOT_COLORS[s], "dim")
                    if self.get(ch, K.SLOT_MUTE[s]) and v:
                        v = p("red", "dim")
                    pads[(r, c)] = v

        else:  # USER: Traktor's LED value picks the palette colour directly
            for r in range(8):
                for c in range(8):
                    pads[(r, c)] = self.get(K.USER_CH, PAD0 + r * 8 + c)

        for key in self.pressed:                                 # touch feedback
            if self.mode != "USER":
                pads[key] = p("white", "full")

        out = {("note", PAD0 + r * 8 + c): v for (r, c), v in pads.items()}
        for i, m in enumerate(MODES):
            out[("cc", CC_LOWER[i])] = p("white", "full") if m == self.mode else p("white", "dim")
        for i in range(4):
            dch = K.DECK_CH[i]
            ph, _ = self.clocks[i].phase(now)
            if self.get(dch, K.TRACK_END) and ph < 0.5:
                v = p("red", "full")
            elif self.get(dch, K.PLAY):
                v = p(DECK_COLORS[i], "full" if ph < 0.25 or i == d else "mid")
            else:
                v = p(DECK_COLORS[i], "mid" if i == d else "dim")
            out[("cc", CC_LOWER[4 + i])] = v
        for unit in range(2):
            on = self.get(K.GLOBAL_CH, K.FX_ON[unit]) > 0
            out[("cc", CC_UPPER[unit * 4])] = p(FX_COLORS[unit], "full" if on else "dim")
            for b in range(3):
                on_b = self.get(K.GLOBAL_CH, K.FX_BUTTON[unit][b]) > 0
                out[("cc", CC_UPPER[unit * 4 + 1 + b])] = p(FX_COLORS[unit], "full" if on_b else "dim")
        out[("cc", CC_PLAY)] = p("green", "full" if playing else ("mid" if blink and ending else "dim"))
        out[("cc", CC_REC)] = p("orange", "full" if self.get(ch, K.CUE) else "dim")
        out[("cc", CC_SHIFT)] = 127 if self.shift else 16
        return out

    def render(self):
        if not self.state:            # Traktor isn't using the bridge mapping: leave the Push alone
            return
        if not self.sent and not self.pal.push1:
            self.push_out.send(mido.Message("sysex", data=SYSEX_HDR + [0x0A, 0x01]))  # User mode
            for m in self.pal.sysex():
                self.push_out.send(m)
        with self.lock:
            out = self.frame(time.monotonic())
        for key, v in out.items():
            if self.sent.get(key) == v:
                continue
            self.sent[key] = v
            kind, n = key
            if kind == "note":
                self.push_out.send(mido.Message("note_on", note=n, velocity=v))
            else:
                self.push_out.send(mido.Message("control_change", control=n, value=v))

    def run(self):
        if not self.pal.push1:        # User mode, so the simple mapping works without pressing User
            self.push_out.send(mido.Message("sysex", data=SYSEX_HDR + [0x0A, 0x01]))
        self.push_in.callback = self.on_push
        self.trak_in.callback = self.on_traktor
        print("Bridge running. Ctrl+C to quit.")
        asked = 0.0
        try:
            while True:
                if not self.state and time.monotonic() - asked > 2:
                    self.press(K.GLOBAL_CH, K.SEND_STATE)       # until Traktor answers, ask for every LED state
                    asked = time.monotonic()
                self.render()
                time.sleep(1 / 30)
        except KeyboardInterrupt:
            for key in self.sent:
                kind, n = key
                msg = (mido.Message("note_on", note=n, velocity=0) if kind == "note"
                       else mido.Message("control_change", control=n, value=0))
                self.push_out.send(msg)


def find_port(names, wanted):
    for n in names:
        if all(w.lower() in n.lower() for w in wanted):
            return n
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--monitor", action="store_true", help="print feedback from Traktor")
    ap.add_argument("--push", default=None, help="part of the Push port name to use")
    ap.add_argument("--push1", action="store_true", help="Push 1 colour table")
    a = ap.parse_args()
    mido.set_backend("mido.backends.rtmidi")
    wanted = [a.push] if a.push else ["push", "user"]
    pin = find_port(mido.get_input_names(), wanted)
    pout = find_port(mido.get_output_names(), wanted)
    if not pin or not pout:
        raise SystemExit("No Push User port found. Ports: %s" % mido.get_input_names())
    push1 = a.push1 or ("push 2" not in pin.lower() and not a.push)
    print("Push: %s (%s)" % (pin, "Push 1" if push1 else "Push 2"))
    Bridge(mido.open_input(pin), mido.open_output(pout), push1, a.monitor).run()


if __name__ == "__main__":
    main()
