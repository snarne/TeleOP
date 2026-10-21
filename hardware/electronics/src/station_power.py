"""Station power, relay and E-stop schematic, plus the USB / CAN topology diagram.

    python hardware/electronics/src/station_power.py
Outputs: out/station_power.{svg,png} and out/usb_can_topology.{svg,png}
"""

import os
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import schemdraw  # noqa: E402
import schemdraw.elements as elm  # noqa: E402
from matplotlib.patches import FancyBboxPatch  # noqa: E402

sys.path.insert(0, os.path.dirname(__file__))
from hgm_board import NET, OUT, Sheet, box  # noqa: E402


def arm_channel(s: Sheet, y: float, side: str, k: str, nc: str):
    """One follower power channel: PSU → fuse → DC SSR → YAM, with the E-stop/relay control loop."""
    psu = box(s, (0.0, y), (2.6, 2.4), right=["+24 V", "0 V"], label=f"PSU {side}\n24 V (I2RT)", label_pos="top")
    p24, p0 = psu["+24 V"], psu["0 V"]
    # load path
    s.w(p24, (2.4, p24[1]))
    s.dot((2.4, p24[1]))
    s.two(elm.Fuse, (2.4, p24[1]), (5.2, p24[1]), f"F{side}  10 A\nATO blade", loc="top")
    ssr = box(s, (9.4, p24[1] - 1.2), (2.6, 4.4), left=["1 (+)", "3 ctl+", "4 ctl−"], right=["2 (−)"],
              label=f"SSR {side}\nCrydom D1D20\n(DC, 20 A)", label_pos="top")
    s.w((5.2, p24[1]), (6.6, p24[1]), (6.6, ssr["1 (+)"][1]), ssr["1 (+)"])
    out = ssr["2 (−)"]
    yam = box(s, (17.0, out[1] - 0.5), (2.8, 2.4), left=["+24 V", "0 V"], label=f"YAM follower {side}\n(DM motors)",
              label_pos="top")
    s.w(out, (13.2, out[1]))
    s.dot((13.2, out[1]))
    s.w((13.2, out[1]), (13.2, yam["+24 V"][1]), yam["+24 V"])
    # TVS across the arm input
    s.two(elm.DiodeTVS, (13.2, out[1]), (13.2, yam["0 V"][1] - 1.6), f"D{side}\nSMDJ28A", loc="bottom", reverse=True)
    # 0 V return
    y0 = yam["0 V"][1] - 1.6
    s.w(p0, (2.0, p0[1]), (2.0, y0), (13.2, y0))
    s.dot((13.2, y0))
    s.w((13.2, y0), (14.6, y0), (14.6, yam["0 V"][1]), yam["0 V"])
    # control loop: +24 V → 0.5 A fuse → E-stop NC → relay K → SSR 3 ; SSR 4 → 0 V
    yc = ssr["3 ctl+"][1]
    s.w((2.4, p24[1]), (2.4, yc + 0.0))
    s.two(elm.Fuse, (2.4, yc), (2.4, yc - 0.0), None) if False else None
    s.two(elm.Switch, (2.4, yc), (4.8, yc), f"E-STOP {nc}\n(NC)", loc="bottom", nc=True)
    s.two(elm.Switch, (4.8, yc), (7.2, yc), f"{k}\nNumato", loc="bottom")
    s.w((7.2, yc), ssr["3 ctl+"])
    yn = ssr["4 ctl−"][1]
    s.w(ssr["4 ctl−"], (7.6, yn), (7.6, y0))
    s.dot((7.6, y0))


def station_power():
    s = Sheet("Station power and safety: relay-commanded DC SSRs, hard-wired E-stop, E-stop sensing")
    s.title_at = (-2.0, 3.2)
    arm_channel(s, 0.0, "L", "K1", "NC1")
    arm_channel(s, -8.5, "R", "K2", "NC2")

    # leader buses
    yl = -16.0
    lp = box(s, (0.0, yl), (2.6, 2.4), right=["+5 V", "0 V"], label="Leader PSU ×2\n5 V 6 A (one per arm)",
             label_pos="top")
    s.two(elm.Fuse, lp["+5 V"], (4.6, lp["+5 V"][1]), "5 A", loc="top")
    s.two(elm.Switch, (4.6, lp["+5 V"][1]), (6.8, lp["+5 V"][1]), "K3 (L) / K4 (R)\nNumato relay", loc="bottom")
    lb = box(s, (11.0, lp["+5 V"][1] - 0.6), (3.6, 2.4), left=["VDD", "GND"],
             label="Leader arm bus\nU2D2 power hub → XL330 chain\n→ J6 spare port → HGM J1", label_pos="top")
    s.w((6.8, lp["+5 V"][1]), (8.0, lp["+5 V"][1]), (8.0, lb["VDD"][1]), lb["VDD"])
    s.w(lp["0 V"], (1.8, lp["0 V"][1]), (1.8, lb["GND"][1] - 0.0), lb["GND"]) if False else None
    s.w(lp["0 V"], (2.0, lp["0 V"][1]), (2.0, lb["GND"][1] - 1.0), (8.6, lb["GND"][1] - 1.0),
        (8.6, lb["GND"][1]), lb["GND"])

    # E-stop sense
    ys = -21.0
    nm = box(s, (1.5, ys), (4.2, 3.2), right=["GPIO0", "VCC 5 V", "GND"],
             label="Numato Lab 8-ch USB relay\n(USB CDC, ASCII commands)", label_pos="top")
    s.w(nm["GPIO0"], (6.4, nm["GPIO0"][1]))
    s.two(elm.Switch, (6.4, nm["GPIO0"][1]), (8.8, nm["GPIO0"][1]), "E-STOP NC3 (sense)", loc="top", nc=True)
    s.w((8.8, nm["GPIO0"][1]), (9.4, nm["GPIO0"][1]), (9.4, nm["GND"][1]), nm["GND"])
    s.dot((5.0, nm["GPIO0"][1])) if False else None
    s.two(elm.Resistor, nm["VCC 5 V"], (5.8, nm["VCC 5 V"][1]), "10 k pull-up", loc="bottom")
    s.w((5.8, nm["VCC 5 V"][1]), (5.8, nm["GPIO0"][1]))
    s.dot((5.8, nm["GPIO0"][1]))
    s.text((11.0, -17.8),
           "E-stop is one mushroom-head, twist-release switch with 3 contact blocks:\n"
           "  NC1 / NC2 break the SSR control loops of the left / right follower, so the cut is\n"
           "  hard-wired and does not depend on the PC, USB or software.\n"
           "  NC3 drives GPIO0 low while released; pressed or a broken wire reads high, which\n"
           "  the station reports as E-STOP (fail-safe sensing).\n"
           "Power-cycle: the station parks the follower, waits for it to settle, opens K1/K2 for\n"
           "  ≥ 3 s, closes them, waits for CAN, and re-initialises.\n"
           "Stop category 0: an unpowered YAM is limp, so it sags under gravity. Teach operators\n"
           "  to park low before pressing, and keep the workspace clear below the arms.\n"
           "TVS SMDJ28A absorbs regenerative / inductive energy when a back-driven arm loses its supply.\n"
           "Relay contacts only carry the SSR control current (≈ 10 mA at 24 V).\n"
           "Ethernet option: Waveshare Modbus POE ETH relay (Modbus TCP) in place of the Numato.")
    s.save("station_power")


def usb_can_topology():
    fig, ax = plt.subplots(figsize=(13.4, 7.2), dpi=150)
    ax.set_xlim(0, 13.4)
    ax.set_ylim(0, 7.2)
    ax.axis("off")

    def node(x, y, w, h, text, fc="#eef3fb", ec="#1f4e9c", size=9.5):
        ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.02,rounding_size=0.08", fc=fc, ec=ec, lw=1.3))
        ax.text(x + w / 2, y + h / 2, text, ha="center", va="center", fontsize=size)
        return (x, y, w, h)

    def link(a, b, label="", color="#3b4350", style="-", lw=1.4):
        ax.annotate("", xy=b, xytext=a, arrowprops=dict(arrowstyle="-", color=color, lw=lw, linestyle=style))
        if label:
            ax.text((a[0] + b[0]) / 2, (a[1] + b[1]) / 2 + 0.07, label, fontsize=8, color=color, ha="center")

    ax.text(0.1, 7.0, "Station USB / CAN / camera topology", fontsize=14, va="top")
    pc = node(5.0, 3.0, 3.0, 1.3, "Station PC (Ubuntu 22.04/24.04)\nteleop-station service\nweb UI :8000",
              fc="#fff4ec", ec="#e8742c", size=10)
    # left: arm side
    items_l = [
        (0.2, 5.6, "CANable → follower L\ncan_follower_l (1 Mbit/s)"),
        (0.2, 4.6, "CANable → follower R\ncan_follower_r (1 Mbit/s)"),
        (0.2, 3.6, "U2D2 → leader L (Dynamixel)\n/dev/dxl_leader_l"),
        (0.2, 2.6, "U2D2 → leader R (Dynamixel)\n/dev/dxl_leader_r"),
        (0.2, 1.6, "HGM L (XIAO RP2040, CDC)\n/dev/hgm_left"),
        (0.2, 0.6, "HGM R (XIAO RP2040, CDC)\n/dev/hgm_right"),
    ]
    hub = node(3.2, 0.45, 1.4, 6.0, "powered\nUSB 2.0\nhub\n(7-port,\nexternal\nsupply)", fc="#f4f6f8", ec="#66707c")
    for x, y, t in items_l:
        node(x, y, 2.6, 0.75, t, size=8.5)
        link((x + 2.6, y + 0.37), (3.2, y + 0.37))
    link((4.6, 3.6), (5.0, 3.6), "")
    # right: cameras + relay
    items_r = [
        (10.2, 5.6, "Wrist camera L, UVC 30 fps\n/dev/v4l/by-id/…-L"),
        (10.2, 4.6, "Wrist camera R, UVC 30 fps\n/dev/v4l/by-id/…-R"),
        (10.2, 3.6, "Overhead camera, UVC 30 fps\n/dev/v4l/by-id/…-top"),
        (10.2, 2.2, "Numato 8-ch USB relay\nK1/K2 SSRs · K3/K4 leaders\nGPIO0 = E-stop sense"),
    ]
    for i, (x, y, t) in enumerate(items_r):
        node(x, y, 2.9, 0.75, t, size=8.5, fc="#eefaf1" if i < 3 else "#eef3fb", ec="#1f6e43" if i < 3 else "#1f4e9c")
        link((8.0, 3.65), (x, y + 0.37), "")
    ax.text(8.55, 5.15, "USB 3 root ports", fontsize=8, color="#1f6e43", rotation=38)
    ax.text(8.6, 2.75, "USB", fontsize=8, color="#3b4350")
    ax.text(10.2, 1.6,
            "Put each camera on its own USB 3 root port (or a hub with\nseparate TTs). Three MJPEG 640×480@30 streams ≈ 3×(5–8) MB/s.",
            fontsize=8, color="#3b4350", va="top")
    ax.text(0.2, 0.3,
            "Persistent names come from udev rules (scripts/udev/99-teleop-station.rules): CAN adapters by serial, U2D2 by FTDI serial,\n"
            "HGMs by RP2040 unique-ID serial, cameras by /dev/v4l/by-id. Each arm's CAN adapter and USB device sit on the arm side of the hub.",
            fontsize=8, color="#3b4350", va="top")
    for ext in ("svg", "png"):
        fig.savefig(os.path.join(OUT, f"usb_can_topology.{ext}"), bbox_inches="tight")
    plt.close(fig)


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    station_power()
    usb_can_topology()
    print("wrote station_power, usb_can_topology")
