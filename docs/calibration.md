# Calibration

Each calibration is a short wizard (**Calibration** page) that writes one YAML file to
`<data_root>/calibration/`. The previous version is kept as `*.prev.yaml`, and every
commit is logged with who did it and when. Each saved episode also stores a snapshot of
all calibrations, so recordings stay interpretable after a re-calibration.

Every wizard also exists as a **standalone script** with this station's ports baked in
(**Generate script** in the UI, or `station calib script <id>`). The scripts only need
`pip install dynamixel-sdk pyserial opencv-python pyyaml numpy`, so you can calibrate on
a laptop without installing the station.

| Wizard | When | Time | You need |
|---|---|---|---|
| Leader arm (per side) | first setup; after rebuilding or re-horning a leader joint | 2 min | nothing |
| Haptic trigger (per side) | first setup; after swapping the spring or the module | 2 min | a 300–800 g weight (water bottle) |
| Gripper force (per side) | first setup; yearly; after a gripper repair | 4 min | force gauge, or a luggage scale and a strap |
| Camera intrinsics (per camera) | first setup; after refocusing or swapping a lens | 3 min | printed ChArUco board |

## Leader arm: joint mapping

The leader is a printed replica of the YAM, so each leader joint maps to the follower
joint with the same index:

```
q_follower[i] = sign[i] · (raw_leader[i] − offset[i])        (then unwrapped into the joint range)
```

**Match-the-follower method** (default when the follower is connected): the follower floats
under gravity compensation, so you can pose it by hand.

1. Pose **both** arms the same way (any pose, elbow bent) and press Capture. The wizard
   averages 30 samples and rejects the capture if the arm moved.
2. Change **every** joint by at least 20° on both arms, keeping them matched, and Capture
   again.
3. Optional: a third matched pose to verify. The wizard reports the residual per joint and
   fails above 4°.

From the two poses, the direction of motion gives each joint's **sign** and the poses give
its **offset**. The wizard also checks that leader and follower moved by the same angle
(ratio 0.85–1.15). A mismatch points to a slipping horn or a wrong gear ratio. Signs that
disagree with `joint_signs` in the config are corrected and reported, so a servo mounted
backwards never needs a code change.

**Known-pose method** (follower offline): zero pose, then the configured `check_pose`.
It's less accurate because it depends on how well you eyeball the zero pose.

## Haptic trigger

| Step | What happens |
|---|---|
| Zero | Hand off. The trigger holds at mid-travel and the module zeroes the spring deflection (δ₀). |
| Released / Squeezed | Captures the lever angle at both ends of travel (θ_open, θ_closed). |
| Stiffness | The trigger holds at mid-travel while a known weight hangs from the finger pad: k_θ = m·g·r_f / deflection. |

The results are written to the module's flash (it keeps them across reboots and stations)
and to `trigger_<side>.yaml`. For the legacy Dynamixel trigger, only the open and closed
travel is calibrated.

## Gripper force

The follower doesn't measure grip force directly. The station estimates it from the
gripper motor's torque:

```
F_grip = G · max(0, |τ| − τ₀)        G ≈ 68.4 N/(N·m) for linear_4310 = motor stroke 6.57 rad / jaw stroke 96 mm
```

The wizard measures free-air friction (τ₀), then squeezes a gauge at three levels. You
type in each reading, and a least-squares fit gives G and the offset. An R² below 0.98
usually means the gauge slipped. Expect G within about 15% of the nominal value. A much
lower G suggests a worn or dirty lead screw.

## Cameras

Download the board (**Download board**, or `station board`) and print it at 100% scale.
Measure a square with a ruler and enter that size. Capture 12 or more views with varied
distance, ±45° tilt, and the board near every corner of the image. You should get an RMS
reprojection error below 0.5 px, and the wizard refuses anything above 1.0 px. The result
is in OpenCV format (`camera_matrix`, `dist_coeffs`), so any training pipeline can undistort.

Wrist-camera hand-eye calibration and overhead extrinsics are on the roadmap. The
recorded follower joint states and the I2RT kinematics already provide everything needed.
