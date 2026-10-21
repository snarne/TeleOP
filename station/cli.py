"""`station` command line.

  station serve [--sim] [--config PATH] [--host 0.0.0.0] [--port 8000]
  station doctor [--config PATH]                 health checks with fixes
  station calib list | script <procedure_id>     standalone calibration scripts
  station power on|off|cycle <channel|all>
  station dxl scan --port /dev/... [--baud 1000000]
  station export --name NAME EPISODE_DIR...      LeRobot dataset from raw episodes
  station board [-o charuco.png]                 printable ChArUco board
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _cfg(args):
    from station.config import load_config

    path = args.config
    if path is None:
        path = ROOT / "config" / ("station.sim.yaml" if getattr(args, "sim", False) else "station.yaml")
    return load_config(path, force_sim=getattr(args, "sim", False))


def cmd_serve(args) -> int:
    import uvicorn

    from station.api import create_app
    from station.orchestrator import Orchestrator

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    cfg = _cfg(args)
    if args.threads:
        cfg.runtime.workers = "thread"
    orch = Orchestrator(cfg)
    orch.start()
    app = create_app(orch)
    print(f"\n  Teleop Station → http://{'localhost' if args.host in ('0.0.0.0', '127.0.0.1') else args.host}:{args.port}"
          f"   ({'SIMULATION' if cfg.station.sim else 'hardware'}, data in {cfg.data_root})\n", flush=True)
    server = uvicorn.Server(uvicorn.Config(app, host=args.host, port=args.port, log_level="warning"))
    try:
        server.run()
    finally:
        orch.shutdown()
    return 0


def cmd_doctor(args) -> int:
    from station.health import run_checks

    cfg = _cfg(args)
    res = run_checks(cfg)
    icon = {"ok": "\033[32m✔\033[0m", "warn": "\033[33m!\033[0m", "error": "\033[31m✘\033[0m", "unknown": "?"}
    group = None
    for c in res["checks"]:
        if c["group"] != group:
            group = c["group"]
            print(f"\n{group.upper()}")
        print(f"  {icon[c['status']]} {c['label']:<28} {c['message']}")
        if c["hint"]:
            print(f"      → {c['hint']}")
    print()
    return 1 if res["worst"] == "error" else 0


def cmd_calib(args) -> int:
    from station.calibration.generator import generate_script

    cfg = _cfg(args)
    ids = [f"{k}_{s}" for s in cfg.enabled_arms() for k in ("leader", "trigger", "gripper")]
    ids += [f"fingertips_{s}" for s in cfg.enabled_arms() if cfg.arms[s].fingertips.backend != "none"]
    ids += [f"camera_{n}" for n in cfg.cameras]
    if args.action == "list" or not args.procedure:
        print("\n".join(ids))
        return 0
    out = Path(args.output) if args.output else cfg.data_root / "calibration" / "scripts"
    r = generate_script(cfg, args.procedure, out)
    print(f"wrote {r['path']}\nrun it with: python3 {r['path']}")
    return 0


def cmd_power(args) -> int:
    from station.hardware.power import PowerManager

    cfg = _cfg(args)
    pm = PowerManager(cfg.power)
    pm.connect()
    if pm.driver is None:
        print(pm.error or "no relay board configured")
        return 1
    if args.action == "cycle":
        pm.set(args.channel, False)
        time.sleep(args.off_s)
        pm.set(args.channel, True)
    else:
        pm.set(args.channel, args.action == "on")
    pm.refresh()
    for c in pm.snapshot()["channels"]:
        print(f"  {c['id']:<16} {c['label']:<24} {'ON' if c['on'] else 'off' if c['on'] is False else '?'}")
    print(f"  e-stop: {pm.estop_ok()}")
    return 0


def cmd_dxl(args) -> int:
    from station.hardware.leader import DynamixelLeader

    bus = DynamixelLeader(args.port, args.baud, [])
    from dynamixel_sdk import COMM_SUCCESS, PacketHandler, PortHandler

    bus._COMM_SUCCESS = COMM_SUCCESS
    bus._port = PortHandler(args.port)
    if not bus._port.openPort() or not bus._port.setBaudRate(args.baud):
        print(f"cannot open {args.port}")
        return 1
    bus._ph = PacketHandler(2.0)
    found = bus.scan()
    for f in found:
        print(f"  ID {f['id']:>3}  {f['model']:<14} fw {f['firmware']}")
    if not found:
        print("  no servos found: check power, baud rate (try 57600) and the cable")
    return 0 if found else 1


def cmd_export(args) -> int:
    from station.db import slugify
    from station.recording.lerobot_export import export

    cfg = _cfg(args)
    root = Path(args.root) if args.root else cfg.data_root / cfg.export.root / slugify(args.name)
    export([Path(p) for p in args.episodes], root, f"{slugify(cfg.station.name)}/{slugify(args.name)}",
           args.fps or cfg.export.fps, cfg.export.video_codec)
    return 0


def cmd_board(args) -> int:
    from station.calibration.charuco import board_png

    Path(args.output).write_bytes(board_png(square_mm=args.square_mm, marker_mm=args.marker_mm))
    print(f"wrote {args.output}: print at 100% scale, then measure a square")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="station", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", type=Path, default=None, help="station YAML (default config/station.yaml)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("serve", help="run the station server + UI")
    s.add_argument("--sim", action="store_true", help="simulate all hardware")
    s.add_argument("--host", default="0.0.0.0")
    s.add_argument("--port", type=int, default=8000)
    s.add_argument("--threads", action="store_true", help="run workers as threads (debugging)")
    s.set_defaults(fn=cmd_serve)

    d = sub.add_parser("doctor", help="check hardware and setup")
    d.add_argument("--sim", action="store_true")
    d.set_defaults(fn=cmd_doctor)

    c = sub.add_parser("calib", help="calibration scripts")
    c.add_argument("action", choices=["list", "script"])
    c.add_argument("procedure", nargs="?")
    c.add_argument("-o", "--output")
    c.add_argument("--sim", action="store_true")
    c.set_defaults(fn=cmd_calib)

    p = sub.add_parser("power", help="relay board")
    p.add_argument("action", choices=["on", "off", "cycle"])
    p.add_argument("channel", default="all", nargs="?")
    p.add_argument("--off-s", type=float, default=3.0)
    p.set_defaults(fn=cmd_power)

    x = sub.add_parser("dxl", help="Dynamixel tools")
    x.add_argument("action", choices=["scan"])
    x.add_argument("--port", required=True)
    x.add_argument("--baud", type=int, default=1_000_000)
    x.set_defaults(fn=cmd_dxl)

    e = sub.add_parser("export", help="export raw episodes to a LeRobot dataset")
    e.add_argument("--name", required=True)
    e.add_argument("--root")
    e.add_argument("--fps", type=int)
    e.add_argument("episodes", nargs="+")
    e.set_defaults(fn=cmd_export)

    b = sub.add_parser("board", help="write a printable ChArUco board")
    b.add_argument("-o", "--output", default="charuco_5x7.png")
    b.add_argument("--square-mm", type=float, default=30.0)
    b.add_argument("--marker-mm", type=float, default=22.0)
    b.set_defaults(fn=cmd_board)

    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
