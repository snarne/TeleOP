"""Haptic Grip Module (HGM): every key dimension in one place.

Units: millimetres and degrees (unless the name says otherwise).

Coordinate frame (shared by every part, the assembly and the docs):
    +Y  the trigger pivot axis, which is also the XC330 output axis. y = 0 is the servo's
        horn mounting face; the servo body lies in y < 0, the drive disc, lever and
        encoder in y > 0.
    +X  forward (the direction the trigger points / the barrel direction).
    +Z  up.
    The pivot axis passes through x = z = 0.

Lever angle phi (deg) is the right-hand rotation about +Y. phi = 0 is the OPEN stop and
phi = +TRAVEL is fully squeezed. The drive disc (servo) angle is phi - delta, where delta
is the spring compression angle (delta = 0: tab resting on the backstop at preload).

Values tagged "VERIFY" depend on vendor drawings. Check them against the ROBOTIS 2D
drawing (emanual.robotis.com → XC330 → Drawings) or measure them before printing.
"""

import math

# ----------------------------------------------------------------------------- servo
SERVO_W = 20.0          # Z extent of the XC330 body
SERVO_L = 34.0          # X extent
SERVO_D = 26.0          # Y extent (horn face to back face)
SERVO_AXIS_FROM_END = 10.0  # VERIFY: output axis to the rear end of the body (X)
HORN_D = 16.0           # VERIFY: horn outer diameter
HORN_T = 3.0            # VERIFY: horn thickness above the case face
HORN_BOLT_PCD = 11.0    # VERIFY: horn bolt circle
HORN_BOLT_N = 4
HORN_BOLT_D = 2.2       # clearance for M2
HORN_CENTER_SCREW_D = 6.0  # relief for the horn's central screw head

# ----------------------------------------------------------------------------- lever / SEA
TRAVEL = 30.0           # lever travel, open → closed (deg)
R_FINGER = 45.0         # effective finger radius r_f
BLADE_ANGLE_OPEN = -60.0  # blade centreline angle at the open stop (deg, in XZ from +X)
BLADE_R_IN = 34.0
BLADE_R_OUT = 56.0
BLADE_T = 5.0           # blade thickness (tangential)
BLADE_Y0 = -15.0        # blade spans y in [BLADE_Y0, LEVER_Y1]

LEVER_Y0 = 6.6          # lever main plate, y range (= pocket floor, so the lever prints flat)
LEVER_Y1 = 12.0
LEVER_HUB_D = 16.0      # hub disc diameter inside the head
LEVER_ARM_W = 8.0       # finger-arm width near the hub

# Spring pack (series-elastic element)
R_T = 20.0              # tangent radius of the spring axis = SEA lever arm R_s
ALPHA_T = 8.0           # angle of the tangent point at mid-deflection (deg, lever frame)
DELTA_MAX = 13.2        # geometric spring-travel span (deg); the overload rim engages ≈12.3°
DELTA_MID = DELTA_MAX / 2
SPRING_OD = 5.5
SPRING_WIRE = 0.9
SPRING_L0 = 15.0        # free length
SPRING_PRELOAD = 0.3    # compression when the tab rests on the backstop
SPRING_N_ACTIVE = 8.5
SPRING_N_TOTAL = 10.5   # closed and ground ends
SPRING_G = 79.3e9       # Pa, music wire (ASTM A228)
SPRING_Y = 11.0         # spring axis y
SPRING_BORE_D = 6.0
POCKET_Y0 = 6.6         # pocket block y range (bridge on top)
POCKET_Y1 = 17.2
BRIDGE_Y0 = 15.5
TAB_W = 7.0             # tab radial width
TAB_T = 4.0             # tab thickness along the spring axis
TAB_Y0 = 3.0
TAB_Y1 = 15.0
SPIGOT_D = 3.4
SPIGOT_L = 2.0
BACKSTOP_T = 3.0
POCKET_HALF_W = 4.6     # half-width of the spring block (bore Ø6 → 1.6 mm walls)
WINDOW_CLEAR = 0.7
RIM_EXTRA = 0.4         # rim set back so the tilted tab edge lands on it

# ----------------------------------------------------------------------------- drive disc
DISC_Y0 = 3.0           # bolts against the horn face
DISC_Y1 = 5.8
DISC_D = 18.0
DISC_BOSS_Y1 = 6.5
DISC_ARM_W = 8.0

# ----------------------------------------------------------------------------- bearings / pin / magnet
B6700_ID, B6700_OD, B6700_W = 10.0, 15.0, 4.0
MR63_ID, MR63_OD, MR63_W = 3.0, 6.0, 2.5
PIN_D, PIN_L = 3.0, 8.0         # Ø3 × 8 dowel, pressed into the drive disc, runs in the MR63 in the lever
MAGNET_D, MAGNET_T = 6.0, 2.5   # diametric N52 disc
FIT_PRESS = 0.05                # added to a bore for a printed press fit
FIT_SLIP = 0.20

# ----------------------------------------------------------------------------- housing
WALL = 2.2
WALL_MIN = 1.6
SPLIT_Y = -3.0                  # clamshell split plane
HEAD_X0, HEAD_X1 = -13.4, 31.0
HEAD_Z0, HEAD_Z1 = -21.5, 20.0
HEAD_Y0 = -28.4                 # outer face, servo side
INNER_PY_WALL = 20.4            # +Y wall inner face (bearing boss protrudes inward to 18.0)
HEAD_Y1 = 22.8                  # outer face, encoder side
BEARING_BOSS_Y0 = 17.6
BEARING_LIP_T = 1.2
BEARING_LIP_D = 12.6
HUB_SHOULDER_D = 11.2
HEAD_FILLET = 6.0

GRIP_TOP_Z = -17.0
GRIP_BOT_Z = -108.0
GRIP_RAKE = 15.0                # deg, bottom sweeps back
GRIP_DEPTH = 34.0               # X
GRIP_WIDTH = 30.0               # Y
GRIP_FRONT_X_TOP = -5.0
GRIP_CY = -3.0                  # grip centre in Y
GRIP_CORNER_R = 11.0
GRIP_SHELL = 2.2

# Stops: the lever arm bears on the housing slot ends
STOP_SLOT_Y0, STOP_SLOT_Y1 = 6.4, 12.6

# Mount (to leader J6)
MOUNT_INSERT_PTS = [(-18.0, 15.0), (12.0, 15.0), (-18.0, -15.0), (12.0, -15.0)]  # (y, z) on the back face
INSERT_D = 3.6                  # M2.5 heat-set insert hole
INSERT_L = 5.0
BOSS_D = 7.0
J6_AXIS_YZ = (-3.0, 10.0)            # J6 roll axis on the back face; raised to clear the hand web
J6_HORN_BOLT_N = 4              # VERIFY / MEASURE on your leader arm
J6_HORN_BOLT_PCD = 11.0         # VERIFY / MEASURE
J6_HORN_BOLT_D = 2.2
J6_HORN_RELIEF_D = 9.0
MOUNT_T = 5.0
MOUNT_STANDOFF = 6.0            # hub length between the flange and the J6 horn
MOUNT_SIZE = 42.0

# Clamshell screws (M2.5 × 12 into heat-set inserts in the +Y half)
SHELL_SCREWS_XZ = [(-8.0, 13.4), (-9.0, -15.0), (26.0, -16.5)]   # head; grip screws are computed in housing.py

# Buttons (Omron D2F-01 micro switches)
D2F_L, D2F_W, D2F_H = 12.8, 5.8, 6.5
BUTTON_A_X, BUTTON_B_X = 8.5, -0.5
BUTTON_Y = -13.0
CAP_STEM_D = 4.0

# HGM v1.1: vibrotactile LRA in the blade
LRA_D, LRA_T = 8.0, 3.2         # VERIFY: coin LRA (e.g. Vybronics VG0832012L / Jinlong G0832012), 235 Hz
LRA_TAPE = 0.25                 # VHB / acrylic tape under the LRA
LRA_Y = -0.5                    # pad centre across the blade width
SKIN_T = 1.0                    # TPU 95A skin over the finger zone
BLADE_BOSS_H = 2.0              # boss on the blade back face behind the LRA pocket
WIRE_GROOVE_W, WIRE_GROOVE_D = 1.4, 1.0   # 2 × 30 AWG silicone leads
WIRE_CLIP_R, WIRE_CLIP_ANG = 12.5, -135.0  # fixed strain-relief post near the pivot (encoder half)

# Encoder cover / AS5600 breakout
AS5600_BOARD = 23.0             # VERIFY: square breakout side length
AS5600_BOARD_T = 1.6
AS5600_AIR_GAP = 1.5            # magnet face → chip (datasheet 0.5–3 mm)
COVER_SIZE = 27.0
COVER_T = 7.0

# Electronics bay
XIAO_L, XIAO_W, XIAO_T = 21.0, 17.5, 1.2
PROTO_W, PROTO_L, PROTO_T = 20.0, 44.0, 1.6
USBC_W, USBC_H = 9.6, 3.9

# ----------------------------------------------------------------------------- materials
DENSITY = {"PLA": 1.24, "PETG": 1.27}   # g/cm3
PRINT_FILL_FACTOR = 0.80   # effective solid fraction (4 perimeters + 30 % infill on thin parts)


# ----------------------------------------------------------------------------- derived
def spring_rate_n_per_mm() -> float:
    d = SPRING_WIRE * 1e-3
    D = (SPRING_OD - SPRING_WIRE) * 1e-3
    return SPRING_G * d**4 / (8 * D**3 * SPRING_N_ACTIVE) / 1000.0


def k_theta_nm_per_rad() -> float:
    return spring_rate_n_per_mm() * 1000.0 * (R_T * 1e-3) ** 2


def spring_compression_mm(delta_deg: float) -> float:
    """Total spring compression (preload included) at relative deflection delta."""
    dm = math.radians(DELTA_MID)
    return SPRING_PRELOAD + R_T * (math.sin(math.radians(delta_deg) - dm) + math.sin(dm))


def finger_force_n(delta_deg: float) -> float:
    f_spring = spring_rate_n_per_mm() * spring_compression_mm(delta_deg)
    return f_spring * R_T / R_FINGER


SPRING_SOLID = SPRING_N_TOTAL * SPRING_WIRE
SPRING_L_INSTALLED = SPRING_L0 - SPRING_PRELOAD
