"""The Push 2 screen: 960x160 pixels over USB (not MIDI), drawn from a snapshot of the bridge's state.

Protocol (Ableton's "Push 2 MIDI and Display Interface Manual"): USB 2982:1967, interface 0, bulk endpoint 0x01.
Each frame is a 16-byte header, then 160 lines of 1024 16-bit pixels (960 shown + 64 filler), pixels as
little-endian BGR565 (red in the low 5 bits), every 4 bytes XORed with E7 F3 E7 FF. The screen goes dark if no
frame arrives for 2 s, so frames are sent continuously. The header must go as its own 16-byte transfer and the
pixels as 16 KB transfers, as in Ableton's sample code: a single long transfer is silently ignored. Ableton Live grabs the screen too: quit Live first.

Needs libusb (Homebrew: brew install libusb), pyusb, Pillow and numpy. Without them the bridge runs without the
screen.
"""
import threading
import time

import numpy as np
from PIL import Image, ImageDraw, ImageFont

W, H = 960, 160
LINE = 2048                     # bytes per line: 960 * 2 + 128 filler
CHUNK = 16384                   # bytes per bulk transfer
HEADER = bytes([0xFF, 0xCC, 0xAA, 0x88] + [0] * 12)
MASK = np.tile(np.array([0xE7, 0xF3, 0xE7, 0xFF], dtype=np.uint8), LINE // 4)
LIBUSB = ["/opt/homebrew/lib/libusb-1.0.0.dylib", "/usr/local/lib/libusb-1.0.0.dylib"]

BG, PANEL, GRID, DIM, TEXT = (0, 0, 0), (18, 18, 22), (40, 40, 48), (90, 90, 100), (235, 235, 240)
RED, AMBER = (255, 40, 40), (255, 170, 30)


def font(size, bold=False):
    for path in (["/System/Library/Fonts/HelveticaNeue.ttc"] if not bold else []) + [
            "/System/Library/Fonts/Helvetica.ttc", "/System/Library/Fonts/SFNS.ttf"]:
        try:
            return ImageFont.truetype(path, size, index=1 if bold and path.endswith(".ttc") else 0)
        except (OSError, ValueError):
            continue
    return ImageFont.load_default()


F_BIG, F_MID, F_SMALL, F_TINY = font(38, True), font(16, True), font(13, True), font(11, True)


def dim(c, k):
    return tuple(int(v * k) for v in c)


# ---------------------------------------------------------------- drawing
def render(view):
    """An RGB image of the screen for `view` (see Bridge.display_view)."""
    img = Image.new("RGB", (W, H), BG)
    g = ImageDraw.Draw(img)
    # top strip: labels for the 8 buttons above the screen (FX1 on + 3 buttons, FX2 on + 3 buttons)
    for u, fx in enumerate(view["fx"]):
        for b in range(4):
            x = (u * 4 + b) * 120
            on = fx["on"] if b == 0 else fx["buttons"][b - 1]
            label = ("FX%d  %d%%" % (u + 1, round(fx["drywet"] * 100))) if b == 0 else "%d" % b
            cell(g, x, 0, label, fx["color"], on)
    # bottom strip: the 8 buttons below the screen send decks A-D to FX1, then FX2
    for i in range(8):
        u, d = divmod(i, 4)
        deck = view["decks"][d]
        cell(g, i * 120, H - 20, "%s > FX%d" % (deck["name"], u + 1), view["fx"][u]["color"], deck["fx"][u])
    for d, deck in enumerate(view["decks"]):
        draw_deck(g, d * 240, 22, deck, view["now"])
    return img


def cell(g, x, y, text, color, on):
    g.rectangle([x + 2, y + 2, x + 117, y + 17], fill=color if on else PANEL, outline=None if on else GRID)
    g.text((x + 60, y + 10), text, font=F_TINY, fill=BG if on else DIM, anchor="mm")


def draw_deck(g, x, y, d, now):
    color = d["color"]
    g.rectangle([x + 2, y, x + 237, y + 115], fill=PANEL)
    # header: deck letter in its colour, then MASTER / SYNC / KEY
    g.rounded_rectangle([x + 8, y + 5, x + 34, y + 27], radius=4, fill=color if d["loaded"] else GRID)
    g.text((x + 21, y + 16), d["name"], font=F_MID, fill=BG, anchor="mm")
    bx = x + 42
    for label, on in (("MASTER", d["master"]), ("SYNC", d["sync"]), ("KEY", d["keylock"])):
        w = g.textlength(label, font=F_TINY) + 10
        g.rounded_rectangle([bx, y + 9, bx + w, y + 24], radius=3, fill=AMBER if on else None,
                            outline=None if on else GRID)
        g.text((bx + w / 2, y + 17), label, font=F_TINY, fill=BG if on else DIM, anchor="mm")
        bx += w + 5
    if not d["loaded"]:
        g.text((x + 120, y + 62), "empty", font=F_MID, fill=DIM, anchor="mm")
        return
    # BPM, live while playing, dimmed when stopped
    bpm = d["bpm"]
    g.text((x + 10, y + 52), "%.1f" % bpm if bpm else "---.-", font=F_BIG,
           fill=TEXT if d["playing"] and bpm else DIM, anchor="lm")
    g.text((x + 150, y + 60), "BPM", font=F_TINY, fill=DIM, anchor="lm")
    # loop: size, lit while looping
    if d["loop"]:
        g.text((x + 228, y + 44), "LOOP " + d["loop"], font=F_SMALL, fill=AMBER if d["in_loop"] else DIM,
               anchor="rm")
    # position bar; red while the end warning is on
    pos = d["pos"]
    g.rectangle([x + 10, y + 76, x + 229, y + 81], fill=GRID)
    if pos is not None:
        end = d["ending"] and (now % 0.5) < 0.25
        g.rectangle([x + 10, y + 76, x + 10 + int(219 * pos), y + 81], fill=RED if end else color)
    # hotcues 1-4 (the Push's cue pads) and the beat in the bar
    for c, t in enumerate(d["cues"]):
        cx = x + 10 + c * 20
        if t:
            g.rectangle([cx, y + 88, cx + 14, y + 100], fill=t)
        else:
            g.rectangle([cx, y + 88, cx + 14, y + 100], outline=GRID)
    for b in range(4):
        bxx = x + 160 + b * 18
        lit = d["playing"] and d["beat"] % 4 == b
        g.ellipse([bxx, y + 89, bxx + 11, y + 100], fill=color if lit else GRID)
    # stems: a bar per stem, height = volume, dark when muted
    if d["stems"]:
        for s in range(4):
            sx = x + 92 + s * 16
            g.rectangle([sx, y + 86, sx + 11, y + 102], outline=GRID)
            if d["stem_on"][s]:
                h = int(15 * d["stem_vol"][s])
                g.rectangle([sx + 1, y + 101 - h, sx + 10, y + 101], fill=d["stem_colors"][s])


# ---------------------------------------------------------------- USB
def encode(img):
    """The 160 masked lines of one frame (send HEADER first, as its own transfer)."""
    a = np.asarray(img, dtype=np.uint16)
    pix = ((a[:, :, 2] >> 3) << 11) | ((a[:, :, 1] >> 2) << 5) | (a[:, :, 0] >> 3)
    lines = np.zeros((H, LINE), dtype=np.uint8)
    lines[:, :W * 2] = pix.astype("<u2").view(np.uint8).reshape(H, W * 2)
    return (lines ^ MASK).tobytes()


class Screen(threading.Thread):
    """Sends render(view()) to the Push about 20 times a second; reconnects if the Push goes away."""

    def __init__(self, view, fps=20):
        super().__init__(daemon=True)
        self.view, self.period = view, 1 / fps
        self.dev = self.ep = None
        self.warned = False

    def connect(self):
        import usb.backend.libusb1
        import usb.core
        import usb.util
        backend = None
        for path in LIBUSB:
            backend = usb.backend.libusb1.get_backend(find_library=lambda _, p=path: p)
            if backend:
                break
        dev = usb.core.find(idVendor=0x2982, idProduct=0x1967, backend=backend)
        if dev is None:
            return False
        usb.util.claim_interface(dev, 0)
        self.dev, self.ep = dev, 0x01
        print("Screen: connected")
        return True

    def run(self):
        while True:
            t0 = time.monotonic()
            try:
                if self.dev is None and not self.connect():
                    time.sleep(2)
                    continue
                data = encode(render(self.view()))
                self.dev.write(self.ep, HEADER, timeout=1000)
                for i in range(0, len(data), CHUNK):
                    self.dev.write(self.ep, data[i:i + CHUNK], timeout=1000)
            except Exception as e:                     # unplugged, Live took it, libusb missing...
                if not self.warned:
                    print("Screen: %s (retrying every 2 s)" % e)
                    self.warned = True
                self.dev = None
                time.sleep(2)
                continue
            self.warned = False
            time.sleep(max(0.0, self.period - (time.monotonic() - t0)))
