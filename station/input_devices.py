"""Physical input devices (USB foot pedals, macro pads) mapped to station actions.

Browser keybindings only work while the UI has focus. A pedal read here with evdev works
regardless, which matters when the operator's hands are on the leader arms.

    inputs:
      - device: /dev/input/by-id/usb-PCsensor_FootSwitch-event-kbd
        bindings: { KEY_A: start_recording, KEY_B: save, KEY_C: abort }
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Callable, List

from station.config import InputDeviceConfig

log = logging.getLogger("station.input")


class InputDevices:
    def __init__(self, devices: List[InputDeviceConfig], do_action: Callable[[str, str], object]):
        self.devices = devices
        self.do_action = do_action
        self._stop = threading.Event()

    def start(self) -> None:
        if not self.devices:
            return
        try:
            import evdev  # noqa: F401
        except ImportError:
            log.warning("inputs configured but python-evdev is missing: pip install evdev")
            return
        for d in self.devices:
            threading.Thread(target=self._run, args=(d,), name=f"input:{d.device}", daemon=True).start()

    def _run(self, cfg: InputDeviceConfig) -> None:
        import evdev

        while not self._stop.is_set():
            try:
                dev = evdev.InputDevice(cfg.device)
                if cfg.grab:
                    dev.grab()
                log.info("input device %s (%s) ready: %s", cfg.device, dev.name, cfg.bindings)
                for ev in dev.read_loop():
                    if self._stop.is_set():
                        break
                    if ev.type == evdev.ecodes.EV_KEY and ev.value == 1:  # key down
                        name = evdev.ecodes.KEY.get(ev.code)
                        name = name[0] if isinstance(name, list) else name
                        action = cfg.bindings.get(name)
                        if action:
                            log.info("pedal %s → %s", name, action)
                            try:
                                self.do_action(action, f"input:{name}")
                            except Exception as e:
                                log.warning("action %s failed: %s", action, getattr(e, "detail", e))
            except (OSError, FileNotFoundError) as e:
                log.warning("input device %s unavailable (%s); retrying in 3 s", cfg.device, e)
                time.sleep(3)

    def stop(self) -> None:
        self._stop.set()
