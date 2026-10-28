"""Drive push_quad.py with a fake Push and a fake Traktor over virtual MIDI ports.

    venv/bin/python tests/sim_quad.py     # exits 1 if any check fails
"""
import os, sys, time, threading, mido
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import contract as K
import push_bridge
import push_quad
push_bridge.PORT_NAME = "Push2 Quad Test"      # don't collide with a running bridge
mido.set_backend("mido.backends.rtmidi")
# fake Push: bridge reads our output, writes to our input
from_bridge = []
fake_in = mido.open_input("Fake Push 2 User Port", virtual=True, callback=from_bridge.append)
fake_out = mido.open_output("Fake Push 2 User Port", virtual=True)
b = push_quad.QuadBridge(False, ["fake push 2", "user"])
threading.Thread(target=b.run, daemon=True).start()
time.sleep(0.5)
# fake Traktor
to_traktor = []
tk_in = mido.open_input("Push2 Quad Test", callback=to_traktor.append)
tk_out = mido.open_output("Push2 Quad Test")
time.sleep(3)
failed = []
def ok(c, m):
    print(("PASS " if c else "FAIL ") + m)
    if not c:
        failed.append(m)
names = [m for m in from_bridge if m.type == "sysex"]
ok(any(list(m.data[-3:]) == [0x0A, 0x01] or list(m.data)[-2:] == [0x0A, 0x01] for m in names), "user mode sysex sent on connect")
ok(any(m.type == "note_on" and m.channel == K.GLOBAL_CH and m.note == K.SEND_STATE for m in to_traktor), "asks Traktor for state")
pad = lambda row, col, v=127: fake_out.send(mido.Message("note_on", note=36 + row*8 + col, velocity=v))
def last_led(note):
    v = [m.velocity for m in from_bridge if m.type == "note_on" and m.note == note]
    return v[-1] if v else None
ok(last_led(36 + 7*8) == b.pal("cyan", "dim"), "waiting view: deck A corner dim cyan")
# Traktor answers: deck A playing, hotcue 1 = cue, stem deck, loop size 1 beat
st = [(0, K.PLAY, 127), (0, K.HOTCUE[0], 1), (0, K.DECK_FLAVOR, K.FLAVOR_STEM), (0, K.LOOP_SIZE_NOW, 5),
      (3, K.SYNC, 127), (0, K.SLOT_MUTE[1], 127)]
for ch, n, v in st: tk_out.send(mido.Message("note_on", channel=ch, note=n, velocity=v))
tk_out.send(mido.Message("note_on", channel=K.GLOBAL_CH, note=K.FX_ON[0], velocity=127))
time.sleep(0.3)
ok(last_led(36 + 4*8 + 0) in (b.pal("green","full"), b.pal("green","mid")), "A play pad green (pulsing)")
ok(last_led(36 + 6*8 + 0) == b.pal("blue","full"), "A hotcue 1 blue")
ok(last_led(36 + 7*8 + 0) == b.pal("orange","full"), "A drums stem orange")
ok(last_led(36 + 7*8 + 1) == 0, "A bass stem muted -> off")
ok(last_led(36 + 5*8 + 0) == b.pal("yellow","mid"), "A loop 1 beat selected")
ok(last_led(36 + 0*8 + 6) == b.pal("blue","full"), "D sync blue")
ok(last_led(36 + 7*8 + 4) == 0, "B stems off (not a stem deck)")
cc = lambda n: ([m.value for m in from_bridge if m.type=="control_change" and m.control==n] or [None])[-1]
ok(cc(102) == b.pal("teal","full"), "FX1 on button lit")
# presses
to_traktor.clear()
pad(4, 0); pad(4, 0, 0); pad(0, 5); time.sleep(0.2)     # A play, D cue down
pad(5, 2); time.sleep(0.2)                                # A loop 4 beats
pad(2, 4); time.sleep(0.2)                                # C hotcue? row2 bottom half = C hotcue 1
sent = [(m.channel, m.note, m.velocity) for m in to_traktor if m.type == "note_on"]
ok((0, K.PLAY, 127) in sent, "A play pad -> deck A play")
ok((3, K.CUE, 127) in sent, "D cue pad -> deck D cue")
ok((0, K.LOOP_SIZE[4], 127) in sent, "A loop pad 3 -> 4-beat loop")
ok((3, K.HOTCUE[0], 127) in sent, "D hotcue 1 pad")
# exit loop by tapping lit size while looping
tk_out.send(mido.Message("note_on", channel=0, note=K.IN_LOOP, velocity=127)); time.sleep(0.2)
to_traktor.clear(); pad(5, 0); time.sleep(0.2)
ok(any(m.note == K.LOOP_ACTIVE for m in to_traktor if m.type=="note_on"), "tap lit loop while looping -> loop off")
# shift + hotcue = delete
to_traktor.clear(); fake_out.send(mido.Message("control_change", control=49, value=127)); pad(6, 1); time.sleep(0.2)
fake_out.send(mido.Message("control_change", control=49, value=0))
ok(any(m.note == K.HOTCUE_DELETE[1] for m in to_traktor if m.type=="note_on"), "shift+hotcue deletes")
# encoders: jog C (encoder 3), touch, FX1 dry/wet
to_traktor.clear()
fake_out.send(mido.Message("note_on", note=2, velocity=127))
fake_out.send(mido.Message("control_change", control=73, value=127))
fake_out.send(mido.Message("control_change", control=75, value=5))
fake_out.send(mido.Message("control_change", control=25, value=127))   # lower button 6 = FX2 assign deck B
time.sleep(0.2)
ok(any(m.type=="note_on" and m.channel==2 and m.note==K.JOG_TOUCH for m in to_traktor), "touch encoder 3 -> deck C scratch")
ok(any(m.type=="control_change" and m.channel==2 and m.control==K.JOG_CC and m.value==127 for m in to_traktor), "encoder 3 -> deck C jog (relative)")
ok(any(m.type=="control_change" and m.channel==K.GLOBAL_CH and m.control==K.FX_DRYWET_CC[0] and m.value==5 for m in to_traktor), "encoder 5 -> FX1 dry/wet")
ok(any(m.type=="note_on" and m.channel==1 and m.note==K.FX2_ASSIGN for m in to_traktor), "lower button 6 -> deck B to FX2")

sys.exit(1 if failed else 0)
