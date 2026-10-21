#!/usr/bin/env python3
"""Bench console for a Haptic Grip Module. It talks the binary protocol directly and
doesn't need the station service.

    python hardware/firmware/tools/hgm_console.py /dev/ttyACM0            # live status
    python hardware/firmware/tools/hgm_console.py /dev/ttyACM0 --mode spring
    python hardware/firmware/tools/hgm_console.py /dev/ttyACM0 --render 5 # 5 N haptic force (holds the watchdog)
    python hardware/firmware/tools/hgm_console.py /dev/ttyACM0 --tare --save
    python hardware/firmware/tools/hgm_console.py /dev/ttyACM0 --set k_theta=3.2 --get k_theta

Requires pyserial. It uses the reference codec from station/hardware/haptic_protocol.py.
"""

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))

import serial  # noqa: E402

from station.hardware import haptic_protocol as hp  # noqa: E402

PARAM_NAMES = {p.name.lower(): p for p in hp.Param}
PARAM_NAMES["preload_nm"] = 13  # v1 extension (firmware ≥ 1.0.0)


def status_str(s: int) -> str:
    return "|".join(f.name for f in hp.Status if s & f) or "-"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("port")
    ap.add_argument("--mode", choices=["off", "spring", "render", "position"], default=None)
    ap.add_argument("--render", type=float, default=None, help="haptic force N (RENDER mode)")
    ap.add_argument("--pos", type=float, default=None, help="POSITION mode target 0..1")
    ap.add_argument("--tare", action="store_true")
    ap.add_argument("--save", action="store_true")
    ap.add_argument("--bootsel", action="store_true", help="reboot into the UF2 bootloader")
    ap.add_argument("--set", action="append", default=[], help="name=value")
    ap.add_argument("--get", action="append", default=[])
    ap.add_argument("--seconds", type=float, default=0.0, help="run time (0 = until Ctrl-C)")
    a = ap.parse_args()

    ser = serial.Serial(a.port, 115200, timeout=0)
    dec = hp.FrameDecoder()
    seq = 0

    def send(pkt):
        nonlocal seq
        ser.write(hp.encode(pkt, seq))
        seq = (seq + 1) & 0xFFFF

    send(hp.Ping())
    for kv in a.set:
        k, v = kv.split("=")
        send(hp.SetParam(int(PARAM_NAMES[k.lower()]), float(v)))
    for k in a.get:
        send(hp.GetParam(int(PARAM_NAMES[k.lower()])))
    if a.tare:
        send(hp.CommandPacket(hp.Command.TARE_SEA))
    if a.bootsel:
        send(hp.CommandPacket(hp.Command.BOOTSEL))
        print("BOOTSEL sent: the module re-enumerates as the RPI-RP2 drive")
        return
    sp = None
    if a.mode or a.render is not None or a.pos is not None:
        mode = hp.Mode[(a.mode or ("render" if a.render is not None else "position")).upper()]
        sp = hp.Setpoint(mode=mode, haptic_n=a.render or 0.0, pos_cmd=a.pos or 0.0, spring_min_n=1.2)

    t0 = time.time()
    last_print = 0.0
    n_tel = 0
    last_tel = None
    last_sp = 0.0
    saved = False
    try:
        while a.seconds <= 0 or time.time() - t0 < a.seconds:
            now = time.time()
            if sp and now - last_sp > 0.008:  # ≥100 Hz setpoints keep the watchdog fed
                send(sp)
                last_sp = now
            if a.save and not saved and now - t0 > (1.0 if a.tare else 0.3):
                send(hp.CommandPacket(hp.Command.SAVE_PARAMS))
                saved = True
            data = ser.read(4096)
            for fr in dec.feed(data):
                p = fr.packet
                if isinstance(p, hp.Telemetry):
                    n_tel += 1
                    last_tel = p
                elif isinstance(p, hp.Info):
                    print(f"INFO fw {p.fw_version} proto {p.proto} hw {p.hw_rev} serial {p.serial} rx_err {p.rx_errors}")
                elif isinstance(p, hp.Log):
                    print(f"LOG[{p.level}] {p.text}")
                elif isinstance(p, hp.Ack):
                    print(f"ACK type=0x{p.req_type:02x} seq={p.req_seq} result={hp.AckResult(p.result).name} value={p.value:.5g}")
            if now - last_print > 0.25 and last_tel:
                rate = n_tel / (now - last_print) if last_print else 0
                t = last_tel
                print(f"\rp={t.pos:5.3f} F_op={t.force_op_n:6.2f}N F_cmd={t.force_cmd_n:6.2f}N "
                      f"θl={t.lever_rad:+.4f} θs={t.servo_rad:+.4f} I={t.servo_ma:5d}mA btn={t.buttons:02b} "
                      f"mode={t.mode} loop={t.loop_us_max:4d}µs {rate:5.0f}Hz [{status_str(t.status)}]   ",
                      end="", flush=True)
                n_tel = 0
                last_print = now
            time.sleep(0.002)
    except KeyboardInterrupt:
        pass
    finally:
        if sp:
            send(hp.Setpoint(mode=hp.Mode.SPRING))
        print()
        ser.close()


if __name__ == "__main__":
    main()
