"""FGS (follower fingertip sensor) design parameters. Change dimensions here only.

Frame ("interface frame", mm), one per finger:
    origin  midpoint of the two M4 holes, on the interface plane (finger flange top face =
            carriage bottom face)
    +z      up, into the gripper
    +y      toward the object (the contact face is at y = CONTACT_Y)
    +x      along the finger width (the stock finger's x)
Both fingers are the same part. The right finger is the left one turned 180° about the gripper z
axis (the stock tip_right.stl is tip_left.stl turned the same way, measured to 0.5 mm).

Stock numbers below were measured from i2rt robot_models/gripper/linear_4310 (gripper.stl,
tip_left.stl, tip_right.stl, linear_4310.xml), not guessed: see docs/hardware/fingertip-sensor.md.
"""

# --------------------------------------------------------------------------- stock interface (measured)
# interface-frame origin in the MuJoCo gripper body frame at q = 0, left finger
LEFT_ORIGIN_G = (-2.21, -17.11, -70.5)
RIGHT_ORIGIN_G = (2.21, 17.11, -70.5)     # and rotated 180° about z
SLIDE_LEFT_G = (0.0, -1.0, 0.0)           # joint7 axis 0 0 -1 in tip_left body → −y in the gripper frame
STROKE = 47.5                             # per finger, joint range 0 … 0.0475 m
M4_X = (-10.5, 10.5)                      # two M4 SHCS, 21.0 mm apart, at y = 0
M4_Y = 0.0
M4_CLEAR_D = 4.5
M4_CBORE_D, M4_UNDER_HEAD = 8.0, 5.0      # stock: Ø7 c'bore, 5.0 mm under the head (reuse the stock screws)
STOCK_FLANGE = dict(x=(-31.7, 36.3), y=(-6.1, 14.9), z=(-12.0, 0.0))
CONTACT_Y = 17.6                          # stock contact face (kept)
TIP_Z = -74.2                             # stock tip bottom (kept)
FINGER_XC = 2.21                          # stock tip centre in x (puts both pads on gripper x = 0)
GRIPPER_BOX = dict(x=(-32.5, 32.5), y=(-51.0, 51.0), z=(-60.0, -46.0))   # rail housing (gripper frame)
GRIPPER_CYL_R, GRIPPER_CYL_Z = 28.5, (-46.0, 10.5)                       # motor can (gripper frame)

# --------------------------------------------------------------------------- materials (g/cm³, MPa)
RHO_AL7075 = 2.81
E_AL7075 = 71700.0
YIELD_AL7075 = 503.0
FATIGUE_AL7075 = 159.0   # rotating-beam endurance, 5e8 cycles (MIL-HDBK-5 class value)
RHO_PETG, RHO_TPU = 1.27, 1.21

# --------------------------------------------------------------------------- finger body
FLANGE_X = (-16.5, 16.5)
FLANGE_Y = (-6.1, 14.9)    # stock flange y range (bearing face on the carriage)
FLANGE_T = 9.0             # z = 0 … −9; c'bore from below leaves M4_UNDER_HEAD under the head
WEB_X = (-9.5, 14.0)       # web width just under the flange; tapers into the neck
NECK_TOP_Z = -30.0
BODY_FRONT_Y = 16.1        # finger front above the pad, 1.5 mm behind the pad surface
NECK_BACK_Y = 3.5          # 1.5 mm behind the flexure back face: seat for the gauge cover
CABLE_CH = (3.2, 1.6)      # cable channel in the neck back face (width, depth)
CABLE_CH_Z = (-30.0, -51.5)

# --------------------------------------------------------------------------- flexure (profile in y–z, cut through x)
# Parallel-guided double beam, no hard stop: the beams are sized to stay elastic with infinite
# fatigue life at the gripper's full force (see fgs_checks.py). The pad sits on a stiff front arm
# whose centre is level with the beam mid-height, so a centred grip puts no axial couple on the
# beams.
B = 12.0                   # width along x (= 12 mm 7075-T6 plate for wire EDM)
NECK_BOTTOM_Z = -51.85
GROUND_H = 5.0             # ground block between neck and beams
BEAM_L = 12.0
BEAM_T = 2.2                # ±0.01 (wire EDM skim cut)
SLOT_W = 2.0               # between the beams
GAP_W = 0.5                # between the front beam and the arm
ARM_T = 4.2
BACK_Y = 5.0               # back face of the rear beam (gauges here)
SLOT_R = 1.0               # full-round slot ends (EDM) = root radius on the inner beam faces
KEYHOLE_R = 0.5            # relief at the bottom of the arm gap: root radius for the front beam's front face
ARM_TOP_GAP = 0.5          # arm top ↔ neck
TIP_CHAMFER_Z = -69.6      # back-bottom chamfer starts below the rear beam
TIP_CHAMFER_Y = 8.6

GROUND_Z = (NECK_BOTTOM_Z, NECK_BOTTOM_Z - GROUND_H)
BEAM_Z = (GROUND_Z[1], GROUND_Z[1] - BEAM_L)
FLOAT_Z = (BEAM_Z[1], TIP_Z)
ARM_TOP_Z = NECK_BOTTOM_Z - ARM_TOP_GAP
BEAM2_Y = (BACK_Y, BACK_Y + BEAM_T)
SLOT_Y = (BEAM2_Y[1], BEAM2_Y[1] + SLOT_W)
BEAM1_Y = (SLOT_Y[1], SLOT_Y[1] + BEAM_T)
GAP_Y = (BEAM1_Y[1], BEAM1_Y[1] + GAP_W)
ARM_Y = (GAP_Y[1], GAP_Y[1] + ARM_T)
FRONT_Y = BODY_FRONT_Y
assert abs(ARM_Y[1] - FRONT_Y) < 1e-6, "y stack must close on the arm front face"
BEAM_MID_Z = (BEAM_Z[0] + BEAM_Z[1]) / 2

# --------------------------------------------------------------------------- pad, gauges, cover
PAD_T = CONTACT_Y - FRONT_Y            # 1.5 mm: 1.0 base + 0.5 ridges, TPU 85A
PAD_RIDGE = (0.5, 1.0)                 # ridge height, pitch (ridges along x: "fingerprints")
PAD_Z = (ARM_TOP_Z - 4.0, TIP_Z + 0.5)
PAD_MARGIN_X = 0.25
GAUGE_GRID = (3.0, 2.4)                # BF350-3AA grid length × width (VERIFY vendor drawing)
GAUGE_BACKING = (5.0, 3.5)             # backing trimmed to 5.0 mm
GAUGE_INSET = 2.0                      # grid centre from the beam root
GAUGE_DX = 2.75                        # two gauges side by side at x_c ± 2.75
GAUGE_FACTOR = 2.0                     # VERIFY lot value (BF350: 2.0–2.2)
COVER_T = 1.2
COVER_SIDE_CLEAR = 0.5
COVER_WALL = 1.0
COVER_Z = (-38.0, TIP_Z - 0.3)
COVER_SIDE_Y = 11.0                    # side walls reach forward to here (protect the gauge wiring)
COVER_SCREW_Z = (-41.0, -48.0)
COVER_SCREW_DX = 3.5
CLIP_Z = (-36.5, -31.0)
CLIP_SCREW_DX = 4.0

# --------------------------------------------------------------------------- loads
F_RANGE = 100.0      # linear sensing range (spec ≥ 80 N)
F_STALL = 480.0      # DM4310 7 N·m peak × 68.4 N/(N·m) (station config gain_n_per_nm)
F_ULT = 500.0        # design ultimate through the stop path

# --------------------------------------------------------------------------- electronics enclosure (gripper frame)
ENC_ANGLE = 0.0      # on the +x side of the motor can
ENC_Z = (-44.0, -14.0)
ENC_W, ENC_D = 34.0, 15.0       # tangential width, radial depth of the box
BOARD = (30.0, 26.0, 1.6)       # protoboard (or 2-layer PCB) footprint
CLAMP_W = 10.0
CLAMP_T = 3.0
