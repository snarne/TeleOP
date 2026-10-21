# Stable device names

Linux numbers USB devices in plug-in order: `/dev/ttyUSB0`, `/dev/video2`, `can1`. Those
numbers change between reboots, so the station config only uses names that can't change.

| Device | Use in `config/station.yaml` | How to find it |
|---|---|---|
| Leader U2D2 | `/dev/serial/by-id/usb-FTDI_USB__-__Serial_Converter_XXXX-if00-port0` | `ls -l /dev/serial/by-id/` (plug in one at a time) |
| Camera | `/dev/v4l/by-id/usb-<camera>-video-index0` | `ls -l /dev/v4l/by-id/` and `v4l2-ctl --list-devices` |
| Two identical cameras | `/dev/v4l/by-path/pci-…-usb-0:3:1.0-video-index0` | by-path depends on the USB port, so label the ports |
| Haptic Grip Module | `/dev/hgm_left`, `/dev/hgm_right` | udev rule keyed on the RP2040 serial (below) |
| CAN adapter | `can_follower_l`, `can_follower_r` | udev rule keyed on the CANable serial (below) |

## CAN adapters

1. Plug in **one** CANable and run `udevadm info -a -p /sys/class/net/can0 | grep -i serial`.
2. Copy the serial into the matching `NAME="can_follower_l"` line in
   `99-teleop-station.rules`, then uncomment it.
3. Repeat for the right arm, then reload:
   `sudo udevadm control --reload-rules && sudo udevadm trigger`, and replug.
4. Check with `ip -details link show can_follower_l`. It should report `state UP` and `bitrate 1000000`.

## Haptic Grip Modules

1. Plug in one module and run `udevadm info -a -n /dev/ttyACM0 | grep '{serial}'`. The
   serial also appears in the station's startup checklist.
2. Fill in the `hgm_left` / `hgm_right` lines and reload the rules as above.

## Checking the U2D2 latency timer

`cat /sys/bus/usb-serial/devices/ttyUSB0/latency_timer` should print `1`.
`station doctor` checks this for every leader.
