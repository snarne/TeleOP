"""HGM carrier-board schematic, drawn with schemdraw on explicit coordinates.

    python hardware/electronics/src/hgm_board.py

Sheets (SVG + PNG in hardware/electronics/out/):
    hgm_1_power.*   5 V input, fuse, TVS, soft-start high-side servo power switch, bus-voltage sense
    hgm_2_dxl.*     half-duplex Dynamixel TTL interface (74LVC2G241) and the servo connector
    hgm_3_mcu.*     XIAO RP2040 pin assignment, AS5600 encoder, I²C pull-ups, thumb buttons
Nets that cross sheets use net labels (tags): 5V_IN, 5V_SERVO, 3V3, DXL_DATA, TX, RX, DIR,
SERVO_EN, SDA, SCL, BTN_A, BTN_B, VSENSE, HSDA, HSCL (v1.1 haptic I²C bus). Every element is placed with explicit endpoints, so
the drawing is deterministic and easy to edit.
"""

import os

import schemdraw
import schemdraw.elements as elm

OUT = os.path.join(os.path.dirname(__file__), "..", "out")
NET = "#1f4e9c"
NOTE = "#3b4350"
schemdraw.config(fontsize=11, lw=1.4)

DIRS = {"left": (-1, 0), "right": (1, 0), "up": (0, 1), "down": (0, -1)}


class Sheet:
    def __init__(self, title: str):
        self.d = schemdraw.Drawing(show=False)
        self.title = title

    def add(self, e):
        self.d.add(e)
        return e

    def w(self, *pts):
        for a, b in zip(pts[:-1], pts[1:]):
            self.add(elm.Line().endpoints(a, b))

    def dot(self, p):
        self.add(elm.Dot().at(p))

    def two(self, cls, a, b, label=None, loc=None, ofst=None, reverse=False, **kw):
        e = cls(**kw).endpoints(a, b)
        if reverse:
            e = e.reverse()
        if label:
            args = {"fontsize": 9.5}
            if loc:
                args["loc"] = loc
            if ofst is not None:
                args["ofst"] = ofst
            e = e.label(label, **args)
        return self.add(e)

    def tag(self, p, name, direction, stub=0.6):
        dx, dy = DIRS[direction]
        q = (p[0] + dx * stub, p[1] + dy * stub)
        if stub:
            self.w(p, q)
        t = getattr(elm.Tag(), direction)().at(q).label(name, fontsize=10, color=NET)
        self.add(t)

    def gnd(self, p, direction="down", stub=0.4):
        dx, dy = DIRS[direction]
        q = (p[0] + dx * stub, p[1] + dy * stub)
        self.w(p, q)
        theta = {"down": 0, "up": 180, "right": 90, "left": 270}[direction]
        self.add(elm.Ground().theta(theta).at(q))

    def text(self, p, s, size=9.5, color=NOTE):
        self.add(elm.Label().at(p).label(s, fontsize=size, halign="left", valign="top", color=color))

    def save(self, name):
        self.add(elm.Label().at(self.title_at).label(self.title, fontsize=13.5, halign="left", valign="bottom"))
        self.d.save(os.path.join(OUT, f"{name}.svg"))
        self.d.save(os.path.join(OUT, f"{name}.png"), dpi=150)


def pins_side(names, side, h):
    n = len(names)
    return [elm.IcPin(name=nm, side=side, pos=1 - (i + 0.5) / n) for i, nm in enumerate(names)], \
        [(0.5 - (i + 0.5) / n) * h * -1 for i in range(n)]


def box(sheet, center, size, left=(), right=(), label="", lblsize=10, pinlblsize=10, numbers=None,
        label_pos="inside"):
    """IC/connector block. Returns {pin name: absolute pin-end point}."""
    w, h = size
    pins = []
    for side, names in (("left", left), ("right", right)):
        n = len(names)
        for i, nm in enumerate(names):
            num = numbers.get(nm) if numbers else None
            inv = nm.startswith("~")
            pins.append(elm.IcPin(name=nm.lstrip("~"), side=side, pos=1 - (i + 0.5) / n, pin=num, invert=inv))
    ic = elm.Ic(pins=pins, size=size, label=label if label_pos == "inside" else "", lblsize=lblsize,
                pinlblsize=pinlblsize).theta(0)
    ic = ic.anchor("center").at(center)
    sheet.add(ic)
    if label and label_pos == "top":
        sheet.add(elm.Label().at((center[0], center[1] + h / 2 + 0.15)).label(
            label, fontsize=lblsize, halign="center", valign="bottom"))
    out = {}
    for nm in list(left) + list(right):
        k = nm.lstrip("~")
        a = ic.absanchors[k]
        out[k] = (float(a[0]), float(a[1]))
    return out


# --------------------------------------------------------------------------- sheet 1


def sheet_power():
    s = Sheet("HGM ① Servo power path (5 V from the leader bus) and bus-voltage sense")
    s.title_at = (-3.5, 2.6)
    j1 = box(s, (-1.7, 0.0), (2.4, 3.0), right=["DATA", "VDD", "GND"],
             label="J1  JST-EH 3P\nfrom leader J6 spare port", numbers={"DATA": "3", "VDD": "2", "GND": "1"},
             label_pos="top")
    # j1 pins: DATA y=+1, VDD 0, GND -1 at x = -1.7 + 1.2 + 0.5 = 0
    xd, yd = j1["DATA"]
    s.w(j1["DATA"], (xd + 0.6, yd))
    s.text((xd + 0.75, yd + 0.25), "n.c.")
    xg, yg = j1["GND"]
    s.w(j1["GND"], (xg + 0.6, yg))
    s.gnd((xg + 0.6, yg), "down")
    # rail
    s.w(j1["VDD"], (0.4, 0))
    s.two(elm.Fuse, (0.4, 0), (3.0, 0), "F1  PTC 1.5 A hold\nMF-MSMF150-2", loc="bottom")
    s.w((3.0, 0), (7.0, 0))
    for x in (4.0, 5.0, 5.5):
        s.dot((x, 0))
    s.two(elm.DiodeTVS, (4.0, 0), (4.0, -2.6), "D1\nSMBJ5.0A", loc="bottom", reverse=True)
    s.gnd((4.0, -2.6), "down", 0.2)
    s.tag((5.5, 0), "5V_IN", "up", 0.7)
    # Q1: source (7, 0), drain (8.5, 0), gate (7.75, -1.37)
    q1 = elm.PFet(bulk=False).theta(270).flip().anchor("source").at((7.0, 0))
    s.add(q1)
    s.text((6.4, 1.9), "Q1  AO3401A\nP-MOSFET, −30 V / 4 A, 44 mΩ")
    s.w((8.5, 0), (12.6, 0))
    for x in (9.5, 11.5):
        s.dot((x, 0))
    s.two(elm.Capacitor, (9.5, 0), (9.5, -2.4), "C2\n470 µF 10 V\nlow-ESR", loc="bottom", polar=True)
    s.gnd((9.5, -2.4), "down", 0.2)
    s.two(elm.Capacitor, (11.5, 0), (11.5, -2.4), "C3\n10 µF X5R", loc="bottom")
    s.gnd((11.5, -2.4), "down", 0.2)
    s.tag((12.6, 0), "5V_SERVO", "right", 0.0)
    # gate network
    g = (7.75, -1.37)
    s.w(g, (7.75, -2.4))
    s.dot((7.75, -2.4))
    s.two(elm.Resistor, (7.75, -2.4), (5.5, -2.4), "R1 10 k", loc="bottom")
    s.w((5.5, -2.4), (5.5, 0))
    s.w((7.75, -2.4), (7.75, -3.8))
    s.dot((7.75, -3.8))
    s.two(elm.Capacitor, (7.75, -3.8), (5.0, -3.8), "C1 1 µF", loc="bottom")
    s.w((5.0, -3.8), (5.0, 0))
    s.two(elm.Resistor, (7.75, -3.8), (7.75, -6.2), "R2 10 k", loc="bottom", ofst=(0.25, 0))
    q2 = elm.BjtNpn(circle=True).theta(0).anchor("collector").at((7.75, -6.2))
    s.add(q2)
    s.text((8.4, -6.3), "Q2\nMMBT3904")
    s.gnd((7.75, -7.59), "down", 0.3)
    s.two(elm.Resistor, (7.0, -6.9), (4.4, -6.9), "R3 4.7 k", loc="top")
    s.dot((4.4, -6.9))
    s.two(elm.Resistor, (4.4, -6.9), (4.4, -9.3), "R4\n100 k", loc="bottom")
    s.gnd((4.4, -9.3), "down", 0.2)
    s.tag((4.4, -6.9), "SERVO_EN", "left", 0.6)
    s.text((10.8, -6.2),
           "SERVO_EN = 1 → Q2 on → Q1 gate ≈ 0 V → servo powered.\n"
           "Turn-on ramp (R1‖R2)·C1 ≈ 5 ms limits inrush into C2.\n"
           "During MCU reset the pin floats; R4 keeps Q2 off,\n"
           "so the servo is unpowered until firmware has pinged it.\n"
           "F1 trips on a wiring fault; D1 clamps bus transients\n"
           "(XC330 absolute maximum 6 V).")
    # bus-voltage sense
    s.tag((18.4, 0), "5V_IN", "left", 0.0)
    s.w((18.4, 0), (19.4, 0))
    s.two(elm.Resistor, (19.4, 0), (19.4, -2.6), "R10\n100 k", loc="bottom")
    s.dot((19.4, -2.6))
    s.two(elm.Resistor, (19.4, -2.6), (19.4, -5.2), "R11\n100 k", loc="bottom")
    s.gnd((19.4, -5.2), "down", 0.2)
    s.w((19.4, -2.6), (21.0, -2.6))
    s.dot((21.0, -2.6))
    s.two(elm.Capacitor, (21.0, -2.6), (21.0, -5.2), "C6\n100 nF", loc="bottom")
    s.gnd((21.0, -5.2), "down", 0.2)
    s.tag((21.0, -2.6), "VSENSE", "right", 0.6)
    s.text((18.2, -6.4), "VSENSE = 5V_IN / 2 → RP2040 ADC0 (D0, v1.1)\n(under-voltage warning)")
    s.save("hgm_1_power")


# --------------------------------------------------------------------------- sheet 2


def sheet_dxl():
    s = Sheet("HGM ② Half-duplex Dynamixel TTL bus to the XC330-M288-T (ID 1, 4 Mbps)")
    s.title_at = (-10.0, 5.6)
    u2 = box(s, (0, 0), (3.2, 4.4), left=["~1OE", "1A", "2Y", "GND"], right=["VCC", "2OE", "1Y", "2A"],
             label="U2  74LVC2G241 (VSSOP-8), VCC = 3.3 V", label_pos="top",
             numbers={"~1OE": "1", "1A": "2", "2Y": "3", "GND": "4", "VCC": "8", "2OE": "7", "1Y": "6", "2A": "5"})
    s.tag(u2["1OE"], "DIR", "left", 0.6)
    y1a, y2y = u2["1A"][1], u2["2Y"][1]
    s.w(u2["1A"], (-4.8, y1a))
    s.dot((-4.8, y1a))
    s.two(elm.Resistor, u2["2Y"], (-4.8, y2y), "R7 22 Ω", loc="bottom")
    s.w((-4.8, y2y), (-4.8, y1a))
    s.w((-4.8, y1a), (-8.6, y1a))
    s.dot((-6.4, y1a))
    s.two(elm.Resistor, (-6.4, y1a), (-6.4, y1a + 2.4), "R5\n10 k", loc="bottom")
    s.tag((-6.4, y1a + 2.4), "3V3", "up", 0.0)
    s.text((-8.3, y1a + 0.55), "DXL_DATA", size=9, color=NET)
    s.gnd(u2["GND"], "down", 0.5) if False else None
    s.w(u2["GND"], (-2.7, u2["GND"][1]))
    s.gnd((-2.7, u2["GND"][1]), "down", 0.4)
    # J2 servo connector
    j2 = box(s, (-10.3, y1a - 1.0), (2.4, 3.0), right=["DATA", "VDD", "GND"],
             label="J2  JST-EH 3P\nto XC330", numbers={"DATA": "3", "VDD": "2", "GND": "1"}, label_pos="top")
    s.w(j2["DATA"], (-8.6, y1a))
    s.tag(j2["VDD"], "5V_SERVO", "right", 0.5)
    s.w(j2["GND"], (-8.3, j2["GND"][1]))
    s.gnd((-8.3, j2["GND"][1]), "down", 0.4)
    # right side
    yv = u2["VCC"][1]
    s.w(u2["VCC"], (3.2, yv))
    s.dot((3.2, yv))
    s.two(elm.Capacitor, (3.2, yv), (3.2, yv + 2.0), "C4\n100 nF", loc="bottom")
    s.gnd((3.2, yv + 2.0), "up", 0.2)
    s.tag((3.2, yv), "3V3", "right", 0.8)
    s.tag(u2["2OE"], "DIR", "right", 0.6)
    yrx = u2["1Y"][1]
    s.w(u2["1Y"], (5.4, yrx))
    s.dot((5.0, yrx))
    s.tag((5.4, yrx), "RX → GP1", "right", 0.0)
    s.two(elm.Resistor, (5.0, yrx), (5.0, yrx - 2.6), "R6\n10 k", loc="bottom")
    s.tag((5.0, yrx - 2.6), "3V3", "down", 0.0)
    s.tag(u2["2A"], "TX ← GP0", "right", 0.6)
    s.text((-10.0, -5.0),
           "DIR = 1 (GP2 high): buffer 2 drives TX onto the bus.   DIR = 0: buffer 2 is Hi-Z and buffer 1 copies the bus to RX.\n"
           "74LVC inputs and Hi-Z outputs tolerate 5 V.  R5 holds the idle bus high; R6 holds RX high while buffer 1 is disabled.\n"
           "R7 damps ringing on the 4 Mbps line.  Firmware sets Return Delay = 0 and Status Return Level = 1, so a 1 kHz tick\n"
           "(1 read + 1 write) uses about 0.2 ms of bus time.  If a long cable gives errors, drop to 2 Mbps (Baud Rate register = 4).")
    s.save("hgm_2_dxl")


# --------------------------------------------------------------------------- sheet 3


def sheet_mcu():
    s = Sheet("HGM ③ MCU (Seeed XIAO RP2040), lever encoder, thumb buttons, v1.1 haptic driver")
    s.title_at = (-7.5, 6.2)
    left = ["D0 · GP26", "D1 · GP27", "D2 · GP28 · A2", "D3 · GP29", "D4 · GP6 · SDA1", "D5 · GP7 · SCL1",
            "D6 · GP0 · TX"]
    right = ["5V (VBUS)", "GND", "3V3", "D10 · GP3", "D9 · GP4", "D8 · GP2", "D7 · GP1 · RX"]
    u1 = box(s, (0, 0), (6.8, 7.0), left=left, right=right, label_pos="top",
             label="U1  Seeed XIAO RP2040 (USB-C → station PC; onboard RGB LED on GP12, its power on GP11)")
    nets_l = ["VSENSE", "BTN_A", "HSDA", "HSCL", "SDA", "SCL", "TX"]      # v1.1 pin map
    nets_r = [None, "GND", "3V3", "BTN_B", "SERVO_EN", "DIR", "RX"]
    for nm, n in zip(left, nets_l):
        if n:
            s.tag(u1[nm], n, "left", 0.6)
        else:
            s.w(u1[nm], (u1[nm][0] - 0.5, u1[nm][1]))
            s.text((u1[nm][0] - 1.7, u1[nm][1] + 0.18), "spare", size=9)
    for nm, n in zip(right, nets_r):
        if n == "GND":
            s.gnd(u1[nm], "right", 0.6)
        elif n:
            s.tag(u1[nm], n, "right", 0.6)
        else:
            s.w(u1[nm], (u1[nm][0] + 0.5, u1[nm][1]))
            s.text((u1[nm][0] + 0.7, u1[nm][1] + 0.18), "n.c. (see note)" if "VBUS" in nm else "spare", size=9)
    # AS5600
    j3 = box(s, (14.2, 1.6), (2.6, 3.6), left=["VCC", "SDA", "SCL", "GND"], right=["DIR"],
             label="J3  AS5600 breakout\nI²C address 0x36", label_pos="top")
    s.tag(j3["VCC"], "3V3", "left", 0.6)
    s.tag(j3["SDA"], "SDA", "left", 0.6)
    s.tag(j3["SCL"], "SCL", "left", 0.6)
    s.gnd(j3["GND"], "left", 0.6)
    s.w(j3["DIR"], (16.4, j3["DIR"][1]))
    s.gnd((16.4, j3["DIR"][1]), "down", 0.3)
    s.text((15.9, 0.9), "DIR → GND\n(sign via the\nlever_dir param)", size=9)
    # I2C pull-ups
    for x, n, ref in ((10.2, "SDA", "R8"), (12.2, "SCL", "R9")):
        s.tag((x, -1.7), "3V3", "up", 0.0)
        s.two(elm.Resistor, (x, -1.7), (x, -4.0), f"{ref}\n2.2 k", loc="bottom")
        s.tag((x, -4.0), n, "down", 0.0)
    # buttons
    for x, n, ref, cref in ((16.4, "BTN_A", "SW1 A", "C5"), (20.4, "BTN_B", "SW2 B", "C7")):
        s.tag((x, -1.6), n, "up", 0.0)
        s.w((x, -1.6), (x, -2.0))
        s.dot((x, -2.0))
        s.two(elm.Button, (x, -2.0), (x, -4.2), f"{ref}\nD2F-01", loc="top")
        s.gnd((x, -4.2), "down", 0.2)
        s.w((x, -2.0), (x + 1.4, -2.0))
        s.two(elm.Capacitor, (x + 1.4, -2.0), (x + 1.4, -4.2), f"{cref}\n100 nF", loc="bottom")
        s.gnd((x + 1.4, -4.2), "down", 0.2)
    # v1.1: DRV2605L haptic driver module on its own I²C bus (≤ 400 kHz) and the LRA in the trigger blade
    u3 = box(s, (28.0, 1.2), (3.0, 4.4), left=["VIN", "GND", "SDA", "SCL", "EN"], right=["OUT+", "OUT−"],
             label="U3  DRV2605L module\n(Adafruit 2305 or equiv.)\nI²C 0x5A", label_pos="top")
    s.tag(u3["VIN"], "3V3", "left", 0.6)
    s.gnd(u3["GND"], "left", 0.6)
    s.tag(u3["SDA"], "HSDA", "left", 0.6)
    s.tag(u3["SCL"], "HSCL", "left", 0.6)
    s.tag(u3["EN"], "3V3", "left", 0.6)
    s.w(u3["OUT+"], (31.4, u3["OUT+"][1]))
    s.w(u3["OUT−"], (31.4, u3["OUT−"][1]))
    s.text((31.6, u3["OUT+"][1] - 0.6), "M1  LRA Ø8 × 3.2,\n~235 Hz (VERIFY part)\nin the trigger blade,\n2 × 30 AWG via\nthe pivot groove", size=9)
    for x, n, ref in ((24.4, "HSDA", "R12"), (26.2, "HSCL", "R13")):
        s.tag((x, -2.6), "3V3", "up", 0.0)
        s.two(elm.Resistor, (x, -2.6), (x, -4.6), f"{ref}\n4.7 k", loc="bottom")
        s.tag((x, -4.6), n, "down", 0.0)
    s.text((-7.5, -6.4),
           "v1.1: the DRV2605L supports Standard/Fast-mode I²C only (≤ 400 kHz), so it has its own bus (I2C0 on D2/D3) while the "
           "AS5600 stays on I2C1 at 1 MHz; VSENSE moved to D0, buttons to D1/D10.\n"
           "Thumb buttons are active-low with the RP2040's internal pull-ups and are debounced in firmware (8 ms); the 100 nF caps "
           "are optional ESD/bounce filters.\n"
           "USB VBUS is NOT connected to 5V_SERVO: the PC powers only the MCU, and the leader's 5 V bus powers the servo. All grounds "
           "(USB, leader bus, servo) are common.\n"
           "R8/R9 (2.2 k, in parallel with the breakout's own pull-ups) give clean edges at 1 MHz Fast-mode Plus I²C.")
    s.save("hgm_3_mcu")


def main():
    os.makedirs(OUT, exist_ok=True)
    sheet_power()
    sheet_dxl()
    sheet_mcu()
    print("wrote hgm_1_power, hgm_2_dxl, hgm_3_mcu")


if __name__ == "__main__":
    main()
