"""Render hardware/electronics/bom.csv as docs/hardware/bom.md, with per-section totals.

    python hardware/electronics/src/bom_md.py
"""

import csv
import os
from collections import OrderedDict

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
CSV = os.path.join(HERE, "..", "bom.csv")
OUT = os.path.join(ROOT, "docs", "hardware", "bom.md")


def main() -> None:
    rows = list(csv.DictReader(open(CSV, encoding="utf-8")))
    sections: "OrderedDict[str, list]" = OrderedDict()
    for r in rows:
        sections.setdefault(r["section"], []).append(r)
    L = ["# Bill of materials", "",
         "Generated from [`hardware/electronics/bom.csv`](../../hardware/electronics/bom.csv) by "
         "`hardware/electronics/src/bom_md.py`. Prices are approximate single-quantity USD (late 2026) for "
         "budgeting only; check the suppliers before ordering.", ""]
    grand = 0.0
    totals = {}
    for sec, items in sections.items():
        L += [f"## {sec}", "", "| Ref | Qty | Part | MPN | Supplier | Unit $ | Line $ | Notes |",
              "|---|---:|---|---|---|---:|---:|---|"]
        tot = 0.0
        for r in items:
            q = float(r["qty"])
            u = float(r["unit_usd"])
            line = q * u
            tot += line
            L.append(f"| {r['ref']} | {r['qty']} | {r['part']} | {r['manufacturer_pn']} | {r['supplier']} | "
                     f"{u:.2f} | {line:.2f} | {r['notes']} |")
        L += [f"| | | **Section total** | | | | **{tot:.2f}** | |", ""]
        totals[sec] = tot
    hgm = next((v for k, v in totals.items() if k.startswith("HGM")), 0.0)
    fgs = next((v for k, v in totals.items() if k.startswith("FGS")), 0.0)
    station = sum(v for k, v in totals.items() if not k.startswith(("HGM", "FGS")))
    grand = 2 * hgm + 2 * fgs + station
    L += ["## Summary", "", "| Item | $ |", "|---|---:|",
          f"| One Haptic Grip Module | {hgm:.2f} |",
          f"| Two HGMs (left + right) | {2 * hgm:.2f} |",
          f"| One fingertip sensor set (FGS, one gripper) | {fgs:.2f} |",
          f"| Two FGS sets (left + right follower) | {2 * fgs:.2f} |",
          f"| Station power, safety and cameras (one-time) | {station:.2f} |",
          f"| **Total for one bimanual station** (excluding the YAM arms, leader arms, PC) | **{grand:.2f}** |", ""]
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    open(OUT, "w", encoding="utf-8").write("\n".join(L))
    print(f"wrote docs/hardware/bom.md: HGM ${hgm:.2f}, FGS ${fgs:.2f}, station ${station:.2f}, total ${grand:.2f}")


if __name__ == "__main__":
    main()
