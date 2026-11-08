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

# Monochrome, black on white, so it reads in daylight and under club lights alike.
PAPER, INK, GREY, LIGHT = (255, 255, 255), (0, 0, 0), (120, 120, 120), (205, 205, 205)
CUE_NAMES = ["SONG", "BREAK", "DROP", "OUTRO"]     # the DJ edits' hot cues 1-4 (dj-tools, Push layout)


def font(size, bold=False):
    for path in (["/System/Library/Fonts/HelveticaNeue.ttc"] if not bold else []) + [
            "/System/Library/Fonts/Helvetica.ttc", "/System/Library/Fonts/SFNS.ttf"]:
        try:
            return ImageFont.truetype(path, size, index=1 if bold and path.endswith(".ttc") else 0)
        except (OSError, ValueError):
            continue
    return ImageFont.load_default()


F_LOOP, F_MID, F_SMALL, F_TINY = font(20, True), font(16, True), font(14, True), font(12, True)
F_TITLE = font(13, True)


def dim(c, k):
    return tuple(int(v * k) for v in c)


# ---------------------------------------------------------------- drawing
def render(view):
    """An RGB image of the screen for `view` (see Bridge.display_view)."""
    img = Image.new("RGB", (W, H), PAPER)
    g = ImageDraw.Draw(img)
    # button strips: each deck's two buttons above the screen (Delay, Reverb) and two below (Flanger, Filter on)
    for d, fx in enumerate(view["fx"]):
        name = view["decks"][d]["name"]
        cell(g, d * 240, 0, "%s %s" % (name, fx["names"][0]), fx["on"][0])
        cell(g, d * 240 + 120, 0, "%s %s" % (name, fx["names"][1]), fx["on"][1])
        cell(g, d * 240, H - 22, "%s %s" % (name, fx["names"][2]), fx["on"][2])
        cell(g, d * 240 + 120, H - 22, "%s FILTER" % name, fx["filter_on"])
    for d, deck in enumerate(view["decks"]):
        if d:
            g.line([d * 240, 24, d * 240, H - 25], fill=LIGHT, width=2)
        draw_deck(g, d * 240, 24, deck, view["fx"][d], view["now"])
    return img


def fit(g, text, f, width):
    """`text`, cut with an ellipsis to fit `width` pixels."""
    if g.textlength(text, font=f) <= width:
        return text
    while text and g.textlength(text + "...", font=f) > width:
        text = text[:-1]
    return text.rstrip() + "..."


def box(g, xy, text, f, on, dim=False):
    """A labelled box: solid black with white text when on, outlined when off (grey when `dim`)."""
    x0, y0, x1, y1 = xy
    if on:
        g.rectangle(xy, fill=INK)
    else:
        g.rectangle(xy, outline=LIGHT if dim else INK, width=1 if dim else 2)
    g.text(((x0 + x1) / 2, (y0 + y1) / 2 + 1), text, font=f, fill=PAPER if on else (GREY if dim else INK), anchor="mm")


def cell(g, x, y, text, on):
    box(g, (x + 3, y + 2, x + 116, y + 19), text, F_SMALL, on)


def draw_deck(g, x, y, d, fx, now):
    # header: deck letter, MASTER / SYNC / KEY, then the BPM (small)
    box(g, (x + 8, y + 2, x + 30, y + 22), d["name"], F_MID, d["loaded"], dim=not d["loaded"])
    bx = x + 36
    for label, on in (("MST", d["master"]), ("SYNC", d["sync"]), ("KEY", d["keylock"])):
        w = g.textlength(label, font=F_TINY) + 10
        box(g, (bx, y + 5, bx + w, y + 20), label, F_TINY, on, dim=not on)
        bx += w + 4
    bpm = d["bpm"]
    g.text((x + 232, y + 13), "%.1f" % bpm if bpm else "---.-", font=F_SMALL,
           fill=INK if d["playing"] and bpm else GREY, anchor="rm")
    if not d["loaded"]:
        g.text((x + 120, y + 60), "empty", font=F_MID, fill=GREY, anchor="mm")
        return
    # title (from Traktor's broadcast tags), cut to fit, then pitch % and key shift
    bits = []
    if d["pitch"] is not None:
        bits.append("%+.1f%%" % d["pitch"])
    if d["key"]:
        bits.append("K%+d" % d["key"])
    bits = " ".join(bits)
    room = 224 - (g.textlength(bits, font=F_TINY) + 8 if bits else 0)
    if d["title"]:
        g.text((x + 8, y + 33), fit(g, d["title"], F_TITLE, room), font=F_TITLE, fill=INK, anchor="lm")
    if bits:
        g.text((x + 232, y + 33), bits, font=F_TINY, fill=INK, anchor="rm")
    # loop size, big; solid while the loop is on. Then stems, then the two knobs: FX amount and filter.
    box(g, (x + 8, y + 43, x + 90, y + 67), ("LOOP " + d["loop"]) if d["loop"] else "LOOP", F_LOOP, d["in_loop"],
        dim=not d["loop"])
    if d["stems"]:
        for s in range(4):
            sx = x + 98 + s * 13
            g.rectangle([sx, y + 43, sx + 9, y + 67], outline=INK)
            if d["stem_on"][s]:
                h = int(23 * d["stem_vol"][s])
                g.rectangle([sx, y + 67 - h, sx + 9, y + 67], fill=INK)
    g.text((x + 232, y + 49), "FX %d%%" % round(fx["amount"] * 100), font=F_SMALL,
           fill=INK if any(fx["on"]) else GREY, anchor="rm")
    flt = fx["filter"]
    label = "FLT --" if flt is None or abs(flt) < 0.02 else ("LP %d" if flt < 0 else "HP %d") % round(abs(flt) * 100)
    g.text((x + 232, y + 63), label, font=F_SMALL, fill=INK if fx["filter_on"] else GREY, anchor="rm")
    # hot cues 1-4 (the Push's cue pads), named, solid when set
    for c, t in enumerate(d["cues"]):
        cx = x + 8 + c * 56
        box(g, (cx, y + 72, cx + 52, y + 94), CUE_NAMES[c], F_TINY, bool(t), dim=not t)
    # position bar; flashes inverted while the end warning is on
    pos = d["pos"]
    end = d["ending"] and (now % 0.5) < 0.25
    g.rectangle([x + 8, y + 99, x + 232, y + 105], fill=INK if end else None, outline=INK)
    if pos is not None:
        g.rectangle([x + 8, y + 99, x + 8 + int(224 * pos), y + 105], fill=PAPER if end else INK)
    # phase meter against the master (centred = in phase), then the beat in the bar
    g.line([x + 88, y + 108, x + 88, y + 113], fill=GREY)
    g.rectangle([x + 8, y + 109, x + 168, y + 112], outline=LIGHT)
    if d["phase"] is not None:
        cx = x + 88 + int(d["phase"] * 158)
        g.rectangle([cx - 7, y + 107, cx + 7, y + 114], fill=INK)
    for b in range(4):
        bxx = x + 178 + b * 14
        lit = d["playing"] and d["beat"] % 4 == b
        g.rectangle([bxx, y + 107, bxx + 9, y + 114], fill=INK if lit else None, outline=INK if lit else LIGHT)


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
