"""MIDI contract between push_bridge.py and the generated Traktor mapping.

Both files import this module, so a change here changes both sides.
MIDI channels are 0-based here (0 = "Ch01" in Traktor).

  Ch01-04   deck A-D commands and feedback
  Ch05      global: FX units, browser, deck focus
  Ch06      16 "free" pads in CUES mode (students map these)
  Ch07      all 64 pads in USER mode (students map these)
  Ch09-12   Remix Deck cells for deck A-D
"""

DECK_CH = [0, 1, 2, 3]
GLOBAL_CH = 4
FREE_CH = 5
USER_CH = 6
CELL_CH = [8, 9, 10, 11]

# --- per-deck notes (channel = deck) ------------------------------------
HOTCUE = list(range(0, 8))          # in: press/hold, out: hotcue type + 1 (0 = empty)
HOTCUE_DELETE = list(range(8, 16))
PLAY = 16
CUE = 17
CUP = 18
SYNC = 19
MASTER = 20
KEYLOCK = 21
FLUX = 22
CENSOR = 23
LOOP_SIZE = list(range(24, 32))     # 1/4, 1/2, 1, 2, 4, 8, 16, 32 beats
LOOP_SIZE_INDEX = [3, 4, 5, 6, 7, 8, 9, 10]   # Traktor index: 0 = 1/32 ... 10 = 32
LOOP_ACTIVE = 32
LOOP_IN = 33
LOOP_OUT = 34
BEATJUMP = [35, 36, 37, 38, 39, 40]  # -16, -4, -1, +1, +4, +16
BEATJUMP_BEATS = [-16, -4, -1, 1, 4, 16]
CUE_PREV = 41
CUE_NEXT = 42
CUE_STORE = 43
CUE_DELETE_CURRENT = 44
FX1_ASSIGN = 45
FX2_ASSIGN = 46
LOAD_TRACK = 47
LOAD_STEMS = 48
FILTER_ON = 49
SLOT_MUTE = [50, 51, 52, 53]
SLOT_FX = [54, 55, 56, 57]
SLOT_STOP = [58, 59, 60, 61]
SLOT_FILTER_ON = [70, 71, 72, 73]
FX_UNIT_ASSIGN_ON = [74, 75, 76, 77]    # in: route this deck to FX unit 1-4 (the bridge gives deck A unit 1 ... D unit 4)
FX_UNIT_ASSIGN_OFF = [78, 79, 80, 81]   # in: take this deck off FX unit 1-4
REMIX_PAGE_DOWN = 66
REMIX_PAGE_UP = 67

# feedback-only notes (Traktor -> bridge)
SLOT_STATE = [62, 63, 64, 65]       # 0 empty .. 4
REMIX_PAGE = 68                     # 0-3
LOOP_SIZE_NOW = 96                  # Traktor loop size index 0-10
DECK_FLAVOR = 97                    # 0 track, 1 remix, 2 stem, 3 live input (Traktor 4.4.2, seen with --monitor)
FLAVOR_REMIX, FLAVOR_STEM = 1, 2
TRACK_END = 98                      # track end warning on/off
BEAT_PHASE = 99                     # 0-127 sawtooth, wraps every beat
DECK_LOADED = 100
IN_LOOP = 101
JOG_TOUCH = 102                     # in: hold = scratch

# per-deck CCs
SLOT_VOLUME_CC = [0, 1, 2, 3]
SLOT_FILTER_CC = [4, 5, 6, 7]
DECK_FILTER_CC = 8
JOG_CC = 9                          # relative 7Fh/01h, straight from a Push encoder
SEEK_POS_CC = 10                    # feedback: play position 0-127 across the track (for the screen)
TEMPO_ADJ_CC = 11                   # feedback: tempo fader, -1..1 -> 0-127 (pitch % = value x tempo range)
PHASE_CC = 12                       # feedback: phase offset to the tempo master, -0.5..0.5 beat -> 0-127
KEY_ADJ_CC = 13                     # feedback: key adjust, -1..1 -> 0-127
TEMPO_RANGE = 103                   # feedback note: tempo range index (TEMPO_RANGES)
TEMPO_RANGES = [2, 4, 6, 8, 10, 12, 14, 16, 18, 20, 25, 35, 50, 100]   # percent

# --- global channel -------------------------------------------------------
FX_ON = [0, 4]                      # unit 1, unit 2
FX_BUTTON = [[1, 2, 3], [5, 6, 7]]
BROWSE_UP = 8
BROWSE_DOWN = 9
TREE_UP = 10
TREE_DOWN = 11
TREE_EXPAND = 12
BROWSER_VIEW = 13
SEND_STATE = 14                     # ask Traktor to resend every output
FOCUS = [16, 17, 18, 19]            # focus deck A-D
FOCUS_NOW = 20                      # feedback: focused deck 0-3
BROADCAST = 21                      # in: switch broadcasting on (for track titles); out: on/off
# per-deck FX (2026-11-02): FX unit N belongs to deck N, in Group mode, effects 1-3 = Delay, Reverb, Flanger
# (picked once in Traktor; a mapping can't choose an effect reliably)
FX_UNIT_SET_ON = [32, 33, 34, 35]   # in: unit 1-4 on
FX_UNIT_GROUP = [36, 37, 38, 39]    # in: unit 1-4 to Group mode (three effects, one button each)
FX_EFFECT = [[40, 41, 42], [43, 44, 45], [46, 47, 48], [49, 50, 51]]   # in/out: effect 1-3 on/off, unit 1-4
FX_DRYWET_CC = [0, 4]
FX_KNOB_CC = [[1, 2, 3], [5, 6, 7]]
FX_UNIT_DRYWET_CC = [16, 17, 18, 19]  # unit 1-4 dry/wet

# Remix cell note = slot * 16 + cell (slot 0-3, cell 0-15) on CELL_CH[deck]
def cell_note(slot, cell):
    return slot * 16 + cell
