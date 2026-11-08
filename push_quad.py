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
                         SYSEX_HDR, COLORS, DECK_COLORS, STEM_COLORS, FX_COLORS, HOTCUE_COLORS,
                         find_port)

try:                                            # the screen is optional: needs pyusb, Pillow, numpy, libusb
    import push_display
except ImportError as e:
    push_display = None
    SCREEN_MISSING = str(e)

import now_playing

QUADRANT = [(4, 0), (4, 4), (0, 0), (0, 4)]     # (first row, first column) of deck A-D
LOOP_PADS = [2, 3, 4, 5]                        # K.LOOP_SIZE positions: 1, 2, 4, 8 beats
LOOP_PAD_COLORS = ["yellow", "lime", "green", "teal"]
# FX per deck: each deck has two knobs (Filter, FX amount), two buttons above the screen (Delay, Reverb) and two
# below (Flanger, Filter on). FX unit N is deck N's, effects 1-3 = Delay, Reverb, Flanger.
FX_NAMES = ["DELAY", "REVERB", "FLANGER"]
LOOP_NAMES = ["1/32", "1/16", "1/8", "1/4", "1/2", "1", "2", "4", "8", "16", "32"]   # Traktor loop size index


def centered(v, half):
    """A 0-127 feedback value for a -half..half range back to that range (63/64 = exactly 0)."""
    if v is None:
        return None
    return 0.0 if v in (63, 64) else (v - 63.5) / 63.5 * half


class QuadBridge(Bridge):
    def __init__(self, monitor, wanted, no_screen=False, no_titles=False):
        super().__init__(None, None, False, monitor)
        self.wanted = wanted
        self.push_name = None
        self.no_screen = no_screen
        self.no_titles = no_titles
        self.titles = [""] * 4        # per deck, from Traktor's broadcast tags (now_playing.py)
        self.started = [0.0] * 4      # when each deck last started playing
        self.broadcast_asked = False
        self.fx_set = False
        self.scratching = set()                       # decks whose jog knob is touched with Shift
        self.state_since = 0.0
        self.resend = []

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
            self.setup()
            # A Push that has just been plugged in (or browned out on USB power) can still be starting up and miss
            # the palette, which leaves the pads on its built-in colours: send it again a little later.
            now = time.monotonic()
            self.resend = [now + 1.5, now + 5]
            print("Push: " + pin)

    def setup(self):
        """User mode, our palette and full brightness, then redraw everything."""
        self.sent = {}
        self.push_out.send(mido.Message("sysex", data=SYSEX_HDR + [0x0A, 0x01]))  # User mode
        for m in self.pal.sysex():
            self.push_out.send(m)

    # ---- Push -> Traktor
    def on_push(self, msg):
        if msg.type in ("note_on", "note_off") and msg.note < 8:   # encoder touch: Shift + a deck's left knob = scratch
            d, k = divmod(msg.note, 2)
            down = msg.type == "note_on" and msg.velocity > 0
            with self.lock:
                if k == 0 and down and self.shift:
                    self.scratching.add(d)
                    self.tap(K.DECK_CH[d], K.JOG_TOUCH, True)
                elif k == 0 and not down and d in self.scratching:
                    self.scratching.discard(d)
                    self.tap(K.DECK_CH[d], K.JOG_TOUCH, False)
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
                self.titles[d] = ""

    def button(self, cc, value):
        down = value > 0
        if cc == CC_SHIFT:
            self.shift = down
        elif cc in CC_UPPER and down:                        # deck A-D: Delay, Reverb
            d, b = divmod(cc - CC_UPPER[0], 2)
            self.press(K.GLOBAL_CH, K.FX_EFFECT[d][b])
        elif cc in CC_LOWER and down:                        # deck A-D: Flanger, Filter on
            d, b = divmod(cc - CC_LOWER[0], 2)
            self.press(*((K.GLOBAL_CH, K.FX_EFFECT[d][2]) if b == 0 else (K.DECK_CH[d], K.FILTER_ON)))
        elif cc == CC_MASTER_ENC:
            up = value > 64
            if self.shift:
                self.press(K.GLOBAL_CH, K.TREE_UP if up else K.TREE_DOWN)
            else:
                self.press(K.GLOBAL_CH, K.BROWSE_UP if up else K.BROWSE_DOWN)
        elif cc in CC_ENC:
            self.encoder(cc - CC_ENC[0], value)

    def encoder(self, i, value):
        d, k = divmod(i, 2)                                  # two knobs per deck: Filter, FX amount
        if k == 0 and self.shift:                            # Shift + Filter knob = jog (7Fh/01h, read directly)
            self.to_traktor("cc", K.DECK_CH[d], K.JOG_CC, value)
            return
        if k == 0:
            ch, cc, start = K.DECK_CH[d], K.DECK_FILTER_CC, 64.0     # centre = filter off
        else:
            ch, cc, start = K.GLOBAL_CH, K.FX_UNIT_DRYWET_CC[d], 0.0
        delta = value if value < 64 else value - 128
        cur = self.enc_value.get((ch, cc), start)
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
                stems = self.get(ch, K.DECK_FLAVOR) == K.FLAVOR_STEM
                for c in range(4):
                    # stem row: solid colour while the stem plays, off when muted or on a non-stem deck
                    on = stems and not self.get(ch, K.SLOT_MUTE[c])
                    pads[(3, c)] = p(STEM_COLORS[c], "full") if on else 0
                    # hotcues: solid in the cue-type colour once set
                    t = self.get(ch, K.HOTCUE[c])
                    pads[(2, c)] = p(HOTCUE_COLORS.get(t, "white"), "full") if t else p("white", "dim")
                    # loops: solid; the active loop full, the selected size mid
                    in_loop = self.get(ch, K.IN_LOOP) > 0
                    current = self.get(ch, K.LOOP_SIZE_NOW, default=None) == K.LOOP_SIZE_INDEX[LOOP_PADS[c]]
                    lvl = ("full" if in_loop else "mid") if current else "dim"
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
        for d in range(4):                                   # FX buttons light in the deck's colour while on
            on = [self.get(K.GLOBAL_CH, n) > 0 for n in K.FX_EFFECT[d]] + [self.get(K.DECK_CH[d], K.FILTER_ON) > 0]
            for b, cc in enumerate((CC_UPPER[2 * d], CC_UPPER[2 * d + 1], CC_LOWER[2 * d], CC_LOWER[2 * d + 1])):
                out[("cc", cc)] = p(DECK_COLORS[d], "full" if on[b] else "dim")
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

    # ---- Traktor -> bridge: remember when decks start, so a new title goes to the right one
    def on_traktor(self, msg):
        kind = "cc" if msg.type == "control_change" else "note"
        n = msg.control if kind == "cc" else getattr(msg, "note", None)
        before = self.state.get((msg.channel, kind, n)) if n is not None else None
        super().on_traktor(msg)
        if kind != "note" or msg.channel not in K.DECK_CH:
            return
        d = K.DECK_CH.index(msg.channel)
        now = self.get(msg.channel, n)
        if n == K.PLAY and now and not before:
            self.started[d] = time.monotonic()
        elif n in (K.DECK_LOADED, K.DECK_FLAVOR) and before is not None and now != before:
            self.titles[d] = ""

    def on_title(self, text):
        """Traktor announced a track: give it to the deck that most recently started playing."""
        with self.lock:
            playing = [d for d in range(4) if self.get(K.DECK_CH[d], K.PLAY)]
            if playing:
                self.titles[max(playing, key=lambda d: self.started[d])] = text

    def ensure_broadcast(self):
        """Switch Traktor's broadcasting on once, so it sends track titles."""
        if self.broadcast_asked or not self.state:
            return
        if not self.state_since:              # give Traktor's full state dump a moment to arrive
            self.state_since = time.monotonic()
        if time.monotonic() - self.state_since < 3:
            return
        self.broadcast_asked = True
        if not self.get(K.GLOBAL_CH, K.BROADCAST):
            self.tap(K.GLOBAL_CH, K.BROADCAST)

    def ensure_fx(self):
        """Once Traktor has answered: FX unit N on, in Group mode, and routed to deck N only."""
        if self.fx_set or not self.state:
            return
        if not self.state_since:
            self.state_since = time.monotonic()
        if time.monotonic() - self.state_since < 3:
            return
        self.fx_set = True
        for d, ch in enumerate(K.DECK_CH):
            self.press(K.GLOBAL_CH, K.FX_UNIT_GROUP[d])
            self.press(K.GLOBAL_CH, K.FX_UNIT_SET_ON[d])
            for u in range(4):
                self.press(ch, K.FX_UNIT_ASSIGN_ON[u] if u == d else K.FX_UNIT_ASSIGN_OFF[u])

    # ---- screen
    def display_view(self):
        """A snapshot of what the screen shows (push_display.render draws it)."""
        now = time.monotonic()
        rgb = lambda name: COLORS[name]
        with self.lock:
            fx = []
            for d, ch in enumerate(K.DECK_CH):
                fx.append({"names": FX_NAMES, "on": [self.get(K.GLOBAL_CH, n) > 0 for n in K.FX_EFFECT[d]],
                           "amount": self.get(K.GLOBAL_CH, K.FX_UNIT_DRYWET_CC[d], "cc") / 127,
                           "filter_on": self.get(ch, K.FILTER_ON) > 0,
                           "filter": centered(self.get(ch, K.DECK_FILTER_CC, "cc", default=None), 1.0)})
            decks = []
            for d, ch in enumerate(K.DECK_CH):
                clock = self.clocks[d]
                _, beat = clock.phase(now)
                fresh = now - clock.last_beat < 2.0
                size = self.get(ch, K.LOOP_SIZE_NOW, default=None)
                pos = self.get(ch, K.SEEK_POS_CC, "cc", default=None)
                decks.append({
                    "name": "ABCD"[d], "color": rgb(DECK_COLORS[d]),
                    "loaded": self.get(ch, K.DECK_LOADED) > 0, "playing": self.get(ch, K.PLAY) > 0,
                    "master": self.get(ch, K.MASTER) > 0, "sync": self.get(ch, K.SYNC) > 0,
                    "keylock": self.get(ch, K.KEYLOCK) > 0, "ending": self.get(ch, K.TRACK_END) > 0,
                    "bpm": 60.0 / clock.period if fresh and clock.count > 2 else None, "beat": beat,
                    "pos": None if pos is None else pos / 127,
                    "loop": LOOP_NAMES[size] if size is not None and size < len(LOOP_NAMES) else "",
                    "in_loop": self.get(ch, K.IN_LOOP) > 0,
                    "cues": [rgb(HOTCUE_COLORS.get(self.get(ch, K.HOTCUE[c]), "white"))
                             if self.get(ch, K.HOTCUE[c]) else None for c in range(4)],
                    "stems": self.get(ch, K.DECK_FLAVOR) == K.FLAVOR_STEM,
                    "stem_on": [not self.get(ch, K.SLOT_MUTE[s]) for s in range(4)],
                    "stem_vol": [self.get(ch, K.SLOT_VOLUME_CC[s], "cc", default=127) / 127 for s in range(4)],
                    "stem_colors": [rgb(c) for c in STEM_COLORS],
                    "title": self.titles[d], "pitch": self.pitch(ch), "key": self.key_shift(ch),
                    "phase": centered(self.get(ch, K.PHASE_CC, "cc", default=None), 0.5)})
            masters = [i for i, dk in enumerate(decks) if dk["master"] and dk["playing"]]
            for dk in decks:              # the phase meter only means something against a playing master
                if not masters or dk["master"] or not dk["playing"]:
                    dk["phase"] = None
        return {"now": now, "fx": fx, "decks": decks}

    def pitch(self, ch):
        adj = centered(self.get(ch, K.TEMPO_ADJ_CC, "cc", default=None), 1.0)
        rng = self.get(ch, K.TEMPO_RANGE, default=None)
        if adj is None or rng is None or rng >= len(K.TEMPO_RANGES):
            return None
        return adj * K.TEMPO_RANGES[rng]

    def key_shift(self, ch):
        adj = centered(self.get(ch, K.KEY_ADJ_CC, "cc", default=None), 1.0)
        return None if adj is None else round(adj * 12)

    def run(self):
        if not self.no_titles:
            now_playing.NowPlaying(self.on_title).start()
        if not self.no_screen:
            if push_display:
                push_display.Screen(self.display_view).start()
            else:
                print("Screen off: %s" % SCREEN_MISSING)
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
                if self.push_out and self.resend and now >= self.resend[0]:
                    self.resend.pop(0)
                    self.setup()
                if not self.no_titles:
                    self.ensure_broadcast()
                self.ensure_fx()
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
    ap.add_argument("--no-screen", action="store_true", help="leave the Push 2 display alone")
    ap.add_argument("--no-titles", action="store_true", help="don't receive track titles or switch broadcasting on")
    a = ap.parse_args()
    mido.set_backend("mido.backends.rtmidi")
    QuadBridge(a.monitor, [a.push] if a.push else ["ableton push 2", "user"], a.no_screen, a.no_titles).run()


if __name__ == "__main__":
    main()
