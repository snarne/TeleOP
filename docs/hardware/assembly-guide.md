# HGM assembly guide (v1.1)

The fingertip sensors for the follower gripper have their own build section in
[fingertip-sensor.md §10](fingertip-sensor.md#10-manufacturing-and-assembly). Start at
[README.md](README.md) for the overall order.

About 2 hours per handle once the parts are printed. Build both (left and right). They
are identical; only the udev name and the station config differ.

![exploded](../../hardware/cad/out/renders/exploded.png)

## Tools

Soldering iron with a heat-set insert tip, calipers, 1.5/2.0 mm hex keys, flush cutters,
Loctite 638 (retaining) and 243 (threadlocker), crimp tool for JST-EH (or a ready-made
ROBOTIS 3-pin cable), a multimeter, and a 0.5 kg + 1.0 kg calibration mass (water bottles
with a scale work).

## 0. Before printing

1. Measure your leader's J6 horn (count the holes, measure the bolt circle with the
   method in `hardware/cad/parts/mount_adapter.py`) and set `J6_HORN_*` in `params.py`.
2. Check the `VERIFY` values against the ROBOTIS XC330 drawing and your AS5600 breakout.
3. Run `python hardware/cad/build.py` and confirm **0 collisions** in `checks.md`.
4. Print the parts (orientations in [haptic-trigger.md §9](haptic-trigger.md#9-printing)).

## 1. Electronics (protoboard v0)

1. Solder U2 onto an MSOP-8 adapter, and Q1/Q2 onto SOT-23 adapters.
2. Place the parts per [protoboard_layout](../../hardware/electronics/out/protoboard_layout.png)
   and wire them point-to-point per the netlist in
   [pinout.md](../../hardware/electronics/pinout.md).
3. **Before you fit the XIAO:** apply 5 V to J1 with a current-limited bench supply
   (300 mA). Check that 5V_SERVO is 0 V and SERVO_EN is floating (R4 pulls Q2 off).
   Short SERVO_EN to 3.3 V through 1 kΩ and check 5V_SERVO ≈ 5 V with a ≈ 5 ms rise on a
   scope.
4. Fit the XIAO. Flash the firmware (`pio run -e xiao_rp2040 -t upload`; hold BOOT while
   plugging in the first time).
5. **v1.1 haptic driver.** Mount the DRV2605L module on the protoboard. Wire VIN and EN
   to 3V3 and GND to GND, then wire SDA → D2 and SCL → D3 with 4.7 k pull-ups (R12, R13)
   and 10 µF at VIN. Leave OUT+/OUT− on a 2-pin header (J4) for the LRA leads. This is the
   v1.1 pin map: VSENSE on D0, buttons on D1/D10 (see
   [pinout.md](../../hardware/electronics/pinout.md)).
6. With no servo attached, run the bring-up console
   `python hardware/firmware/tools/hgm_console.py /dev/ttyACM0`. It should show the INFO
   packet, a `servo not found` LOG and, once the AS5600 is plugged in, the ENCODER_OK
   status bit. Attach the servo, power-cycle, and check `hgm ready` and SERVO_OK. With
   the LRA connected, boot gives a ≈ 1 s auto-calibration buzz and sets LRA_OK (status
   bit 9). If the DRV2605L is missing or calibration fails, a LOG says so and cues stay
   off. Nothing else changes.

## 2. Mechanics

1. **Inserts.** Heat-set the M2.5 inserts into the encoder half's 5 clamshell bosses and
   the 4 back-face mount holes, and the M2 inserts into the 2 encoder-cover bosses and the
   lever arm (blade screw).
2. **Drive disc.** Press the Ø3 × 8 dowel into the disc centre with a drop of Loctite 638
   until it stands 5.7 mm above the centre boss (it bottoms on the horn-screw relief). Bolt the disc to the XC330 horn with
   4 × M2 × 4 button heads (Loctite 243).
3. **Lever.** Press the MR63 into the hub's inner seat and glue the magnet into the shaft
   end (CA glue). Its diametric axis is any orientation; the station calibrates it.
4. **Spring.** Drop the spring into the lever's U-channel. Slide the lever onto the
   disc's tab and pin. The tab spigot enters the spring and the pin enters the MR63. The
   spring is now preloaded 0.3 mm against the backstop.
5. **Buttons, then servo, into the servo half.** Drop the two button caps into the
   top-wall holes from inside (flange down). Push the two D2F switches into the cradle
   pockets from below, then seat the servo in its cradle (horn toward the split face).
   The servo body holds the switches, and the switches hold the caps.
6. **Bearing.** Press the 6700ZZ into the encoder half's seat from outside until it sits
   on the inner lip.
7. **Close.** Feed the lever hub through the bearing from inside the encoder half. Lay the
   board into the rails in the servo half, connect J2 (servo) and J3 (encoder), route the
   J1 lead out through the back-face cable hole, then close the halves with 5 × M2.5 × 16.
   The lever must swing freely between its stops with no rubbing.
8. **Encoder cover.** Fit the AS5600 board into the cover (chip facing the magnet; 1.5 mm
   air gap is set by the pocket) and screw the cover on with 2 × M2 × 6. Its ring retains
   the bearing.
9. **Blade and LRA (v1.1).**
   1. Feed the two 30 AWG LRA leads (0.25 m) through the Ø1.6 hole from the blade pocket
      to the top face. Stick the LRA into the pocket on a Ø8 disc of 0.25 mm VHB tape,
      leads down the hole.
   2. Press the leads into the blade's top groove and slide the blade onto the arm end,
      fixing it with 1 × M2 × 6.
   3. Lay the leads in the lever arm's groove toward the pivot. Leave a 15 mm slack loop
      around the pivot, then snap them into the slotted clip post on the encoder half
      (strain relief) and solder them to J4.
   4. Swing the lever through its full travel and check that the leads never pull taut.
   5. Stretch the TPU skin over the blade's finger zone (a drop of CA at each end).
10. **Mount.** Screw the mount adapter to the leader's J6 horn (M2 × 6), then the housing
    to the adapter (4 × M2.5 × 8 from the J6 side). Plug J1's lead into J6's spare JST
    port.

![placement](../../hardware/cad/out/renders/placement.png)

## 3. Bring-up and calibration

1. Plug the HGM into the station hub. `ls -l /dev/hgm_*` should show it (after running
   the udev setup in the station README).
2. In the station UI → **Calibration → Trigger (left/right)**, run the wizard: directions,
   tare (hand off), travel (rest and full squeeze), k_θ with the 0.5/1.0 kg masses, then
   save. The wizard rejects a k_θ outside 2.0–4.5 N·m/rad, which usually means the spring
   isn't seated.
3. **Diagnostics → Haptics.** Squeeze in SPRING mode. The force trace should be smooth
   from ≈ 1.2 N at rest, with a loop time under 400 µs and 500 Hz telemetry.
4. Enable RENDER with the follower gripping a firm object. Feedback should rise smoothly;
   if it buzzes, lower `feedback_gain` or raise `damping`.

## 4. Maintenance

* The LRA leads flex at the pivot. Check them yearly: if LRA_OK drops or the cues go
  quiet, re-solder or replace the leads (a 15-minute job with the blade off).

* Replace the spring every ~1 M full-scale cycles (≈ $1.50). It's a 5-minute job: remove
  the encoder cover, open the clamshell, and swap.
* If k_θ drifts by more than 10 % between calibrations, check for spring set or a
  cracked lever pocket.
