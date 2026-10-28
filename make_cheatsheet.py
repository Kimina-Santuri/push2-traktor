"""Draw docs/cheatsheet.svg: the four-deck layout (push_quad.py) as a one-page diagram.

    python3 make_cheatsheet.py      -> writes docs/cheatsheet.svg

Edit the tables below when the layout in push_quad.py changes.
"""
import os
from xml.sax.saxutils import escape

HERE = os.path.dirname(os.path.abspath(__file__))

C = {"cyan": "#00c8ff", "orange": "#ff7a1a", "purple": "#9b5cff", "lime": "#9be22d",
     "green": "#22d36b", "teal": "#14c9a4", "blue": "#3d7bff", "yellow": "#ffcc1a",
     "magenta": "#ff3fd2", "red": "#ff3b3b", "pink": "#ff6f9c", "white": "#f2f2f2",
     "grey": "#5b5f66"}
DARK_TEXT = {"blue", "purple", "grey", "red", "magenta"}       # these fills get white text

DECKS = [("A", "cyan"), ("B", "orange"), ("C", "purple"), ("D", "lime")]
QUAD_ROWS = [                                                  # top to bottom inside a corner
    [("Drums", "orange"), ("Bass", "yellow"), ("Other", "cyan"), ("Vocals", "magenta")],
    [("Cue 1", "grey"), ("Cue 2", "grey"), ("Cue 3", "grey"), ("Cue 4", "grey")],
    [("Loop 1", "yellow"), ("Loop 2", "lime"), ("Loop 4", "green"), ("Loop 8", "teal")],
    [("PLAY", "green"), ("CUE", "orange"), ("SYNC", "blue"), ("LOAD", None)],
]
KNOBS = [("Jog A", "Deck A", "cyan"), ("Jog B", "Deck B", "orange"), ("Jog C", "Deck C", "purple"),
         ("Jog D", "Deck D", "lime"), ("FX1 Dry/Wet", "⇧ FX1 Knob 2", "teal"),
         ("FX1 Knob 1", "⇧ FX1 Knob 3", "teal"), ("FX2 Dry/Wet", "⇧ FX2 Knob 2", "pink"),
         ("FX2 Knob 1", "⇧ FX2 Knob 3", "pink")]
UPPER = [("FX1 On", "teal"), ("FX1 B1", "teal"), ("FX1 B2", "teal"), ("FX1 B3", "teal"),
         ("FX2 On", "pink"), ("FX2 B1", "pink"), ("FX2 B2", "pink"), ("FX2 B3", "pink")]
LOWER = [("A → FX1", "teal"), ("B → FX1", "teal"), ("C → FX1", "teal"), ("D → FX1", "teal"),
         ("A → FX2", "pink"), ("B → FX2", "pink"), ("C → FX2", "pink"), ("D → FX2", "pink")]

LEGEND = [
    ("Transport", [("green", "Play: pulses on the beat while playing"),
                   ("red", "Play flashes red: track is ending"),
                   ("orange", "Cue: hold to preview, CDJ style"),
                   ("blue", "Sync on"),
                   ("cyan", "Load: deck colour when a track is loaded")]),
    ("Hotcues", [("grey", "Empty: tap to set"),
                 ("blue", "Cue (solid once set)"), ("yellow", "Fade-in"), ("orange", "Fade-out"),
                 ("lime", "Load"), ("white", "Grid"), ("green", "Loop")]),
    ("Stems (stem decks only)", [("orange", "Drums   ·   yellow Bass   ·   cyan Other   ·   magenta Vocals"),
                                 ("grey", "Off: muted (tap to toggle), or the deck has no stems")]),
    ("Loops", [("green", "Half-lit size = selected; fully lit while looping"),
               ("teal", "Tap the lit size again to exit the loop")]),
]
SHIFT = ["⇧ + Hotcue: delete it", "⇧ + Stem: stem FX send on/off", "⇧ + Load: load as stems",
         "⇧ + Knobs 5–8: FX knobs 2 and 3", "⇧ + Master knob: folder tree"]


class SVG:
    def __init__(self):
        self.parts = []

    def add(self, s):
        self.parts.append(s)

    def rect(self, x, y, w, h, fill, rx=6, stroke=None, sw=0, opacity=1):
        st = ' stroke="%s" stroke-width="%s"' % (stroke, sw) if stroke else ""
        self.add('<rect x="%g" y="%g" width="%g" height="%g" rx="%g" fill="%s" opacity="%g"%s/>'
                 % (x, y, w, h, rx, fill, opacity, st))

    def text(self, x, y, s, size=12, fill="#e8e8e8", weight=400, anchor="middle"):
        self.add('<text x="%g" y="%g" font-size="%g" font-weight="%d" fill="%s" text-anchor="%s">%s</text>'
                 % (x, y, size, weight, fill, anchor, escape(s)))


def fill_text(name):
    return "#ffffff" if name in DARK_TEXT else "#111111"


def draw():
    W, H = 1440, 1130
    s = SVG()
    s.rect(0, 0, W, H, "#121316", rx=0)
    s.text(40, 46, "Push 2 × Traktor Pro 4 — four-deck cheat sheet", 26, "#ffffff", 700, "start")
    s.text(40, 70, "push_quad.py + Push2 Bridge.tsi · each 4×4 corner of the pads is one deck",
           14, "#9aa0a8", 400, "start")

    # Push body
    bx, by, bw, bh = 30, 90, 880, 1020
    s.rect(bx, by, bw, bh, "#1c1d21", rx=18, stroke="#2c2e33", sw=2)
    pad, gap = 76, 8
    pitch = pad + gap
    gx = 130                                      # first pad column
    split = 16                                    # extra space between the decks
    col_x = [gx + i * pitch + (split if i >= 4 else 0) for i in range(8)]
    span = col_x[7] + pad - col_x[0]

    # knobs
    ky = 135
    for i, (top, sub, col) in enumerate(KNOBS):
        cx = col_x[i] + pad / 2
        s.add('<circle cx="%g" cy="%g" r="24" fill="#2a2c31" stroke="%s" stroke-width="4"/>'
              % (cx, ky, C[col]))
        s.add('<line x1="%g" y1="%g" x2="%g" y2="%g" stroke="#d0d0d0" stroke-width="3" stroke-linecap="round"/>'
              % (cx, ky - 8, cx, ky - 20))
        s.text(cx, ky + 44, top, 12, "#ffffff", 600)
        s.text(cx, ky + 60, sub, 10.5, "#9aa0a8")
    mx = col_x[7] + pad + 50
    s.add('<circle cx="%g" cy="%g" r="20" fill="#2a2c31" stroke="#f2f2f2" stroke-width="3"/>' % (mx, ky))
    s.text(mx, ky + 44, "Browse", 12, "#ffffff", 600)
    s.text(mx, ky + 60, "⇧ Tree", 10.5, "#9aa0a8")
    s.text(col_x[0] + 2 * pitch - gap / 2 + 40, 104, "touch knobs 1–4 and turn to scratch · turn without touching to nudge",
           11, "#9aa0a8")

    # buttons above the screen, screen, buttons below
    uy, sy, ly = 218, 262, 340
    for i, (label, col) in enumerate(UPPER):
        s.rect(col_x[i], uy, pad, 32, C[col], rx=5)
        s.text(col_x[i] + pad / 2, uy + 21, label, 11.5, fill_text(col), 700)
    s.rect(col_x[0], sy, span, 66, "#07080a", rx=6, stroke="#2c2e33", sw=1)
    s.text(col_x[0] + span / 2, sy + 30, "screen not used", 13, "#5b5f66")
    s.text(col_x[0] + span / 2, sy + 50, "upper buttons: FX units on/off + buttons · lower buttons: send a deck to FX1 / FX2",
           11, "#5b5f66")
    for i, (label, col) in enumerate(LOWER):
        s.rect(col_x[i], ly, pad, 32, C[col], rx=5, opacity=0.9)
        s.text(col_x[i] + pad / 2, ly + 21, label, 11.5, fill_text(col), 700)

    # pads
    py0 = 400
    row_y = [py0 + r * pitch + (split if r >= 4 else 0) for r in range(8)]   # 0 = top row
    for qi, (deck, dcol) in enumerate(DECKS):
        qr, qc = divmod(qi, 2)
        x0, y0 = col_x[qc * 4], row_y[qr * 4]
        s.rect(x0 - 5, y0 - 5, 4 * pitch - gap + 10, 4 * pitch - gap + 10, "none", rx=10,
               stroke=C[dcol], sw=3)
        for r, row in enumerate(QUAD_ROWS):
            for c, (label, col) in enumerate(row):
                col = col or dcol
                x, y = col_x[qc * 4 + c], row_y[qr * 4 + r]
                s.rect(x, y, pad, pad, C[col], rx=7)
                s.text(x + pad / 2, y + pad / 2 + 5, label, 13, fill_text(col), 700)
        # deck tag in the side margin
        tx = bx + 50 if qc == 0 else col_x[7] + pad + 50
        ty = y0 + 2 * pitch - gap / 2
        s.add('<circle cx="%g" cy="%g" r="26" fill="%s"/>' % (tx, ty - 6, C[dcol]))
        s.text(tx, ty + 4, deck, 28, "#111111", 800)
        s.text(tx, ty + 40, "DECK", 11, C[dcol], 700)

    # Shift
    s.rect(bx + 18, row_y[7] + 20, 64, 36, "#f2f2f2", rx=5)
    s.text(bx + 50, row_y[7] + 43, "⇧ Shift", 12, "#111111", 700)

    # legend
    lx, y = 940, 120
    for title, items in LEGEND:
        s.text(lx, y, title, 16, "#ffffff", 700, "start")
        y += 12
        for col, label in items:
            y += 24
            s.rect(lx, y - 14, 18, 18, C[col], rx=4)
            s.text(lx + 28, y, label, 13, "#d6d8dc", 400, "start")
        y += 34
    s.text(lx, y, "Shift (⇧) combos", 16, "#ffffff", 700, "start")
    y += 12
    for line in SHIFT:
        y += 24
        s.text(lx, y, line, 13, "#d6d8dc", 400, "start")
    y += 46
    s.text(lx, y, "Each corner, top to bottom", 16, "#ffffff", 700, "start")
    for line in ["1  Stems: mute drums / bass / other / vocals", "2  Hotcues 1–4",
                 "3  Loops: 1, 2, 4, 8 beats", "4  Play · Cue · Sync · Load"]:
        y += 24
        s.text(lx, y, line, 13, "#d6d8dc", 400, "start")
    y += 46
    s.text(lx, y, "Corners glowing dim in the deck colours = script running,", 12, "#9aa0a8", 400, "start")
    s.text(lx, y + 18, "waiting for Traktor (check In/Out port: Push2 Traktor Bridge).", 12, "#9aa0a8", 400, "start")

    body = "\n".join(s.parts)
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %d %d" width="%d" height="%d" '
            'font-family="-apple-system, BlinkMacSystemFont, \'Helvetica Neue\', Arial, sans-serif">\n'
            '<title>Push 2 × Traktor four-deck cheat sheet</title>\n%s\n</svg>\n' % (W, H, W, H, body))


if __name__ == "__main__":
    os.makedirs(os.path.join(HERE, "docs"), exist_ok=True)
    out = os.path.join(HERE, "docs", "cheatsheet.svg")
    open(out, "w").write(draw())
    print("wrote " + out)
