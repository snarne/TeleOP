"""Protoboard (HGM v0) placement plan: a 20 × 44 mm board, 0.1" grid, 7 columns × 17 rows.

    python hardware/electronics/src/protoboard.py   → out/protoboard_layout.{svg,png}

Parts go on the top side, and wiring is point-to-point on the bottom with 30 AWG Kynar,
following the netlist in pinout.md. The XIAO sits at the bottom end so its USB-C lines up
with the grip opening.
"""

import os

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import FancyBboxPatch, Rectangle  # noqa: E402

OUT = os.path.join(os.path.dirname(__file__), "..", "out")
P = 2.54
COLS, ROWS = 7, 17
X0, Y0 = (20.0 - (COLS - 1) * P) / 2, (44.0 - (ROWS - 1) * P) / 2

# (label, col0, row0, cols, rows, colour, pins[(col,row,name)])
PARTS = [
    ("U1  XIAO RP2040\n(castellated, on 2×7 headers)", 0, 0, 7, 8, "#2f3a4a", []),
    ("U2\n74LVC2G241\non MSOP-8→DIP\nadapter", 0, 9, 4, 4, "#1f6e43",
     [(0, 9, "1"), (0, 10, "2"), (0, 11, "3"), (0, 12, "4"), (3, 12, "5"), (3, 11, "6"), (3, 10, "7"), (3, 9, "8")]),
    ("Q1 AO3401A\nSOT-23 adapter", 4, 9, 3, 1, "#7a3e9d", [(4, 9, "G"), (5, 9, "S"), (6, 9, "D")]),
    ("Q2 MMBT3904\nSOT-23 adapter", 4, 11, 3, 1, "#7a3e9d", [(4, 11, "B"), (5, 11, "E"), (6, 11, "C")]),
    ("C2 470 µF\n6.3 mm radial", 4, 13, 2, 2, "#2f5f9e", [(4, 14, "+"), (5, 14, "−")]),
    ("J1 5 V in\nJST-EH 3P", 0, 14, 3, 1, "#b5651d", [(0, 14, "G"), (1, 14, "V"), (2, 14, "D")]),
    ("J2 servo\nJST-EH 3P", 0, 16, 3, 1, "#b5651d", [(0, 16, "G"), (1, 16, "V"), (2, 16, "D")]),
    ("J3 AS5600\n1×4", 3, 16, 4, 1, "#b5651d", [(3, 16, "V"), (4, 16, "G"), (5, 16, "SDA"), (6, 16, "SCL")]),
    ("F1 PTC\n1812", 6, 13, 1, 2, "#8a8a8a", []),
]
PASSIVES = "R1–R11, C1, C3, C4, C6 (0805 or ¼ W) fill the remaining holes and the underside; see the netlist."


def main():
    os.makedirs(OUT, exist_ok=True)
    fig, ax = plt.subplots(figsize=(7.5, 11), dpi=150)
    ax.add_patch(Rectangle((0, 0), 20, 44, fc="#d8c48a", ec="#7a6a3a", lw=1.5))
    for c in range(COLS):
        for r in range(ROWS):
            ax.add_patch(plt.Circle((X0 + c * P, Y0 + r * P), 0.45, fc="#b8862f", ec="#6b4e1b", lw=0.4))
    for label, c0, r0, nc, nr, col, pins in PARTS:
        x = X0 + c0 * P - P / 2 + 0.15
        y = Y0 + r0 * P - P / 2 + 0.15
        ax.add_patch(FancyBboxPatch((x, y), nc * P - 0.3, nr * P - 0.3, boxstyle="round,pad=0.0,rounding_size=0.5",
                                    fc=col, ec="black", lw=0.8, alpha=0.82))
        ax.text(x + nc * P / 2 - 0.15, y + nr * P / 2 - 0.15, label, color="white", fontsize=6.3, ha="center",
                va="center", weight="bold")
        for (pc, pr, nm) in pins:
            ax.text(X0 + pc * P, Y0 + pr * P - 0.95, nm, fontsize=4.8, ha="center", color="#fff6d8")
    # USB-C overhang marker
    ax.add_patch(Rectangle((10 - 4.5, -2.2), 9.0, 3.2, fc="#9aa3ad", ec="black", lw=0.8))
    ax.text(10, -0.6, "USB-C (overhangs the board end → grip opening)", fontsize=6, ha="center", va="center")
    ax.annotate("toward the grip top / head", xy=(10, 46.5), xytext=(10, 45.2), fontsize=7, ha="center",
                arrowprops=dict(arrowstyle="->"))
    ax.text(-0.5, -4.2, "HGM v0 protoboard placement plan (top view; 20 × 44 mm, 0.1\" grid)", fontsize=9.5,
            ha="left", weight="bold")
    ax.text(-0.5, -5.6, PASSIVES, fontsize=7, ha="left")
    ax.text(-0.5, -6.9, "Mount: the board slides into the rails in the servo-half grip; components face +Y (the split plane).",
            fontsize=7, ha="left")
    ax.set_xlim(-1.5, 21.5)
    ax.set_ylim(-7.8, 47.5)
    ax.set_aspect("equal")
    ax.axis("off")
    for ext in ("svg", "png"):
        fig.savefig(os.path.join(OUT, f"protoboard_layout.{ext}"), bbox_inches="tight")
    plt.close(fig)
    print("wrote protoboard_layout")


if __name__ == "__main__":
    main()
