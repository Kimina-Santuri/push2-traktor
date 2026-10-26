"""Push 2 -> Traktor, four decks at once: each 4x4 corner of the pads is one deck.

    python3 push_quad.py              # run (or let the login item run it)
    python3 push_quad.py --monitor    # also print everything Traktor sends

Uses the same Traktor mapping as push_bridge.py ("Push2 Bridge.tsi", port
"Push2 Traktor Bridge"), so only run one of the two. The virtual port stays up
while the Push is unplugged and the Push is picked up again when it comes back.

    Deck A | Deck B        each corner, top to bottom:
    -------+-------          stems     drums  bass   other  vocals
    Deck C | Deck D          hotcues   1      2      3      4
                             loops     1      2      4      8 beats
                             transport play   cue    sync   load
"""
import argparse
import time

import mido

import contract as K
from push_bridge import (Bridge, PAD0, CC_SHIFT, CC_LOWER, CC_UPPER, CC_ENC, CC_MASTER_ENC,
                         SYSEX_HDR, DECK_COLORS, STEM_COLORS, FX_COLORS, HOTCUE_COLORS,
                         find_port)

QUADRANT = [(4, 0), (4, 4), (0, 0), (0, 4)]     # (first row, first column) of deck A-D
LOOP_PADS = [2, 3, 4, 5]                        # K.LOOP_SIZE positions: 1, 2, 4, 8 beats
LOOP_PAD_COLORS = ["yellow", "lime", "green", "teal"]
FX_KNOBS = [(0, 0), (0, 1), (1, 0), (1, 1)]     # encoders 5-8: (unit, 0 = dry/wet / 1 = knob 1)


class QuadBridge(Bridge):
    def __init__(self, monitor, wanted):
        super().__init__(None, None, False, monitor)
        self.wanted = wanted
        self.push_name = None

    # ---- Push hot-plug
    def connect(self):
        """Open the Push if it's there, drop it if it went away. Called every 2 s."""
        names = mido.get_input_names()
        if self.push_name and self.push_name not in names:
            print("Push unplugged, waiting for it")
            self.push_in.close()
            self.push_out.close()
            self.push_in = self.push_out = self.push_name = None
        if self.push_name:
            return
        pin = find_port(names, self.wanted)
        pout = find_port(mido.get_output_names(), self.wanted)
        if pin and pout:
            self.push_out = mido.open_output(pout)
            self.push_in = mido.open_input(pin, callback=self.on_push)
            self.push_name = pin
            self.sent = {}
            self.push_out.send(mido.Message("sysex", data=SYSEX_HDR + [0x0A, 0x01]))  # User mode
            for m in self.pal.sysex():
                self.push_out.send(m)
            print("Push: " + pin)

    # ---- Push -> Traktor
    def on_push(self, msg):
        if msg.type in ("note_on", "note_off") and msg.note < 4:   # touching encoders 1-4 = scratch
            with self.lock:
                self.tap(K.DECK_CH[msg.note], K.JOG_TOUCH, msg.type == "note_on" and msg.velocity > 0)
            return
        if msg.type == "pitchwheel":
            return
        super().on_push(msg)

    def pad(self, row, col, down):
        key = (row, col)
        (self.pressed.add if down else self.pressed.discard)(key)
        d = (0 if row >= 4 else 2) + (col >= 4)
        ch = K.DECK_CH[d]
        r, c = row % 4, col % 4
        if r == 3 and down:                                  # stems: mute, Shift = FX send
            self.press(ch, (K.SLOT_FX if self.shift else K.SLOT_MUTE)[c])
        elif r == 2:                                         # hotcues, Shift = delete
            if self.shift:
                if down:
                    self.press(ch, K.HOTCUE_DELETE[c])
            else:
                self.tap(ch, K.HOTCUE[c], down)
        elif r == 1 and down:                                # loops: tap the lit size again to exit
            i = LOOP_PADS[c]
            if self.get(ch, K.IN_LOOP) and self.get(ch, K.LOOP_SIZE_NOW, default=None) == K.LOOP_SIZE_INDEX[i]:
                self.press(ch, K.LOOP_ACTIVE)
            else:
                self.press(ch, K.LOOP_SIZE[i])
        elif r == 0:
            if c == 0 and down:
                self.press(ch, K.PLAY)
            elif c == 1:
                self.tap(ch, K.CUE, down)                    # CDJ cue: hold to preview
            elif c == 2 and down:
                self.press(ch, K.SYNC)
            elif c == 3 and down:
                self.press(ch, K.LOAD_STEMS if self.shift else K.LOAD_TRACK)

    def button(self, cc, value):
        down = value > 0
        if cc == CC_SHIFT:
            self.shift = down
        elif cc in CC_LOWER and down:                        # FX1 for A-D, then FX2 for A-D
            unit, d = divmod(cc - CC_LOWER[0], 4)
            self.press(K.DECK_CH[d], K.FX2_ASSIGN if unit else K.FX1_ASSIGN)
        elif cc in CC_UPPER and down:
            unit, b = divmod(cc - CC_UPPER[0], 4)
            self.press(K.GLOBAL_CH, K.FX_ON[unit] if b == 0 else K.FX_BUTTON[unit][b - 1])
        elif cc == CC_MASTER_ENC:
            up = value > 64
            if self.shift:
                self.press(K.GLOBAL_CH, K.TREE_UP if up else K.TREE_DOWN)
            else:
                self.press(K.GLOBAL_CH, K.BROWSE_UP if up else K.BROWSE_DOWN)
        elif cc in CC_ENC:
            self.encoder(cc - CC_ENC[0], value)

    def encoder(self, i, value):
        if i < 4:                                            # jog: Traktor reads 7Fh/01h directly
            self.to_traktor("cc", K.DECK_CH[i], K.JOG_CC, value)
            return
        unit, k = FX_KNOBS[i - 4]
        if self.shift:                                       # Shift: knobs 2 and 3 of the unit
            cc = K.FX_KNOB_CC[unit][1 + k]
        else:
            cc = K.FX_DRYWET_CC[unit] if k == 0 else K.FX_KNOB_CC[unit][0]
        ch = K.GLOBAL_CH
        delta = value if value < 64 else value - 128
        cur = self.enc_value.get((ch, cc), 0.0)
        new = max(0.0, min(127.0, cur + delta))
        self.enc_value[(ch, cc)] = new
        if int(new) != int(cur):
            self.to_traktor("cc", ch, cc, int(new))

    # ---- LEDs
    def frame(self, now):
        p = self.pal
        out = {}
        waiting = not self.state
        for d, (r0, c0) in enumerate(QUADRANT):
            ch = K.DECK_CH[d]
            phase, _ = self.clocks[d].phase(now)
            pulse = "full" if phase < 0.25 else "mid"
            blink = phase < 0.5
            pads = {}
            if waiting:                                      # bridge is up, Traktor hasn't answered
                for r in range(4):
                    for c in range(4):
                        pads[(r, c)] = p(DECK_COLORS[d], "dim")
            else:
                playing = self.get(ch, K.PLAY) > 0
                ending = self.get(ch, K.TRACK_END) > 0
                stems = self.get(ch, K.DECK_FLAVOR) == 1
                for c in range(4):
                    if not stems:
                        pads[(3, c)] = p("white", "dim")
                    elif self.get(ch, K.SLOT_MUTE[c]):
                        pads[(3, c)] = p("red", "dim")
                    else:
                        fx = self.get(ch, K.SLOT_FX[c]) > 0
                        pads[(3, c)] = p(STEM_COLORS[c], pulse if fx else "full")
                    t = self.get(ch, K.HOTCUE[c])
                    pads[(2, c)] = p(HOTCUE_COLORS.get(t, "white"), "full" if t else "dim")
                    in_loop = self.get(ch, K.IN_LOOP) > 0
                    current = self.get(ch, K.LOOP_SIZE_NOW, default=None) == K.LOOP_SIZE_INDEX[LOOP_PADS[c]]
                    lvl = (pulse if in_loop else "mid") if current else "dim"
                    pads[(1, c)] = p(LOOP_PAD_COLORS[c], lvl)
                if ending and playing:
                    pads[(0, 0)] = p("red", "full" if blink else "dim")
                else:
                    pads[(0, 0)] = p("green", pulse if playing else "dim")
                pads[(0, 1)] = p("orange", "full" if self.get(ch, K.CUE) else "dim")
                pads[(0, 2)] = p("blue", "full" if self.get(ch, K.SYNC) else "dim")
                pads[(0, 3)] = p(DECK_COLORS[d], "mid" if self.get(ch, K.DECK_LOADED) else "dim")
            for (r, c), v in pads.items():
                row, col = r0 + r, c0 + c
                if (row, col) in self.pressed:
                    v = p("white", "full")
                out[("note", PAD0 + row * 8 + col)] = v
        for d in range(4):
            ch = K.DECK_CH[d]
            for unit in range(2):
                on = self.get(ch, K.FX2_ASSIGN if unit else K.FX1_ASSIGN) > 0
                out[("cc", CC_LOWER[unit * 4 + d])] = p(FX_COLORS[unit], "full" if on else "dim")
        for unit in range(2):
            on = self.get(K.GLOBAL_CH, K.FX_ON[unit]) > 0
            out[("cc", CC_UPPER[unit * 4])] = p(FX_COLORS[unit], "full" if on else "dim")
            for b in range(3):
                on_b = self.get(K.GLOBAL_CH, K.FX_BUTTON[unit][b]) > 0
                out[("cc", CC_UPPER[unit * 4 + 1 + b])] = p(FX_COLORS[unit], "full" if on_b else "dim")
        out[("cc", CC_SHIFT)] = 127 if self.shift else 16
        return out

    def render(self):
        if not self.push_out:
            return
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
        self.trak_in.callback = self.on_traktor
        print("Quad bridge running on port '%s'. Ctrl+C to quit." % "Push2 Traktor Bridge")
        asked = checked = 0.0
        try:
            while True:
                now = time.monotonic()
                if now - checked > 2:
                    checked = now
                    try:
                        self.connect()
                    except Exception as e:           # a half-enumerated USB device; try again
                        print("Push connect failed: %s" % e)
                if not self.state and now - asked > 2:
                    self.press(K.GLOBAL_CH, K.SEND_STATE)
                    asked = now
                self.render()
                time.sleep(1 / 30)
        except KeyboardInterrupt:
            if self.push_out:
                for kind, n in self.sent:
                    self.push_out.send(mido.Message("note_on", note=n, velocity=0) if kind == "note"
                                       else mido.Message("control_change", control=n, value=0))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--monitor", action="store_true", help="print feedback from Traktor")
    ap.add_argument("--push", default=None, help="part of the Push port name to use")
    a = ap.parse_args()
    mido.set_backend("mido.backends.rtmidi")
    QuadBridge(a.monitor, [a.push] if a.push else ["ableton push 2", "user"]).run()


if __name__ == "__main__":
    main()
