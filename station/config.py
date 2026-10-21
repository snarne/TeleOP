"""Station configuration: one YAML file describes the whole cell.

`config/station.yaml` is the hardware template; `config/station.sim.yaml` runs everything
simulated. Paths in the config may use `~` and are resolved relative to the config file.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, List, Literal, Optional

import yaml
from pydantic import BaseModel, Field, model_validator

SIDES = ("left", "right")


class FollowerConfig(BaseModel):
    backend: Literal["i2rt", "sim"] = "i2rt"
    can_channel: str = "can_follower_l"
    arm_type: str = "yam"
    gripper_type: str = "linear_4310"
    rest_pose: List[float] = Field(default_factory=lambda: [0.0, 0.0, 0.0, 0.0, 0.0, 0.0])
    max_joint_speed: float = 3.0          # rad/s, command rate limit while tracking
    engage_speed: float = 0.6             # rad/s, slow-move speed when teleop engages
    max_tracking_error: float = 0.6       # rad, sustained error above this → fault
    # The gripper's full usable force. A full squeeze of the trigger commands this much, so
    # operators can use the gripper's whole range. 50 N is i2rt's default for linear_4310;
    # raise it to what I2RT rates your gripper for (check with Calibration → Gripper force).
    max_grip_force_n: float = 50.0
    gripper_limits: Optional[List[float]] = None  # [closed, open] raw motor rad; None → i2rt auto-calibrates
    gravity_comp_factor: Optional[List[float]] = None


class LeaderConfig(BaseModel):
    backend: Literal["dynamixel", "sim"] = "dynamixel"
    port: str = "/dev/serial/by-id/CHANGE_ME_left_leader"
    baudrate: int = 1_000_000
    joint_ids: List[int] = Field(default_factory=lambda: [1, 2, 3, 4, 5, 6])
    # Default joint signs for a YAM-replica leader; the calibration wizard verifies/corrects them.
    joint_signs: List[int] = Field(default_factory=lambda: [1, 1, 1, 1, 1, 1])
    calibration_file: str = "calibration/leader_left.yaml"
    # The leader's "zero pose" must match the follower's zero pose. A second check pose
    # validates signs and offsets during calibration.
    check_pose: List[float] = Field(default_factory=lambda: [0.0, 1.0472, 1.0472, 0.0, 0.0, 0.0])


class TriggerConfig(BaseModel):
    # hgm = Haptic Grip Module (series-elastic trigger, own MCU)
    # dynamixel_legacy = original trigger servo on the leader bus (position + weak current-mode feedback)
    backend: Literal["hgm", "dynamixel_legacy", "sim", "none"] = "hgm"
    port: str = "/dev/hgm_left"
    legacy_id: int = 7
    legacy_open_ticks: int = 2048
    legacy_closed_ticks: int = 2700
    legacy_base_current_ma: int = 40
    legacy_max_current_ma: int = 300
    calibration_file: str = "calibration/trigger_left.yaml"


class GripperForceConfig(BaseModel):
    """Follower grip-force estimate F = gain * max(0, |tau| - tau_friction)."""

    gain_n_per_nm: float = 68.4           # linear_4310: motor_stroke / gripper_stroke = 6.57 / 0.096
    tau_friction_nm: float = 0.12
    contact_on_n: float = 2.5
    contact_off_n: float = 1.2
    still_speed: float = 0.5              # normalized gripper units / s
    filter_hz: float = 25.0
    calibration_file: str = "calibration/gripper_left.yaml"


class FingertipConfig(BaseModel):
    """Follower fingertip force sensors (FGS, docs/hardware/fingertip-sensor.md). With them, haptic
    feedback is driven by the true contact force at the object, and slip is detected at the pads."""

    backend: Literal["fgs", "sim", "none"] = "none"
    port: str = "/dev/fgs_left"
    contact_on_n: float = 0.8
    contact_off_n: float = 0.4
    calibration_file: str = "calibration/fingertips_left.yaml"


class ArmConfig(BaseModel):
    enabled: bool = True
    power_channel: Optional[str] = None          # relay channel feeding this follower
    leader_power_channel: Optional[str] = None   # relay channel feeding this leader bus + HGM servo
    follower: FollowerConfig = Field(default_factory=FollowerConfig)
    leader: LeaderConfig = Field(default_factory=LeaderConfig)
    trigger: TriggerConfig = Field(default_factory=TriggerConfig)
    gripper_force: GripperForceConfig = Field(default_factory=GripperForceConfig)
    fingertips: FingertipConfig = Field(default_factory=FingertipConfig)


class CameraConfig(BaseModel):
    label: str = ""
    backend: Literal["opencv", "realsense", "sim"] = "opencv"
    device: str = "/dev/video0"           # prefer /dev/v4l/by-id/... for stable naming
    serial: Optional[str] = None          # RealSense serial
    width: int = 640
    height: int = 480
    fps: int = 30
    fourcc: str = "MJPG"
    latency_ms: float = 0.0               # subtracted from capture timestamps
    calibration_file: str = ""
    attached_to: Optional[str] = None     # "left" / "right" for wrist cameras


class PowerChannel(BaseModel):
    id: str
    label: str
    relay: int


class PowerConfig(BaseModel):
    backend: Literal["numato", "lcus", "modbus_tcp", "sim", "none"] = "none"
    port: str = "/dev/ttyACM0"            # numato / lcus
    host: str = "192.168.1.200"           # modbus_tcp
    tcp_port: int = 502
    unit_id: int = 1
    channels: List[PowerChannel] = Field(default_factory=list)
    estop_input: Optional[int] = None     # relay-board GPIO / discrete input wired to the e-stop aux contact
    estop_ok_level: int = 0               # input level that means "e-stop released" (NC to GND + pull-up)
    boot_wait_s: float = 3.0              # wait after power-on before connecting


class RecordingConfig(BaseModel):
    video_codec: str = "libx264"
    video_crf: int = 23
    video_preset: str = "ultrafast"
    preview_fps: int = 15
    preview_width: int = 640
    telemetry_compression: Literal["zstd", "lz4", "none"] = "zstd"


class ExportConfig(BaseModel):
    fps: int = 30
    root: str = "datasets"                # relative to data_root
    video_codec: str = "h264"             # passed to LeRobot (h264 is fast; libsvtav1 is smaller)
    python: Optional[str] = None          # interpreter with `lerobot` installed (default: this one)


class InputDeviceConfig(BaseModel):
    """A USB foot pedal / macro keypad read directly (works even when the browser isn't focused)."""

    device: str                            # /dev/input/by-id/...-event-kbd
    bindings: Dict[str, str] = Field(default_factory=dict)  # evdev key name → action, e.g. KEY_A: save
    grab: bool = True                      # exclusive: keys don't also type into other apps


class RuntimeConfig(BaseModel):
    workers: Literal["process", "thread"] = "process"
    control_hz: float = 200.0
    state_hz: float = 20.0


class StationInfo(BaseModel):
    name: str = "Teleop Station"
    data_root: str = "~/teleop_data"
    sim: bool = False


class StationConfig(BaseModel):
    station: StationInfo = Field(default_factory=StationInfo)
    runtime: RuntimeConfig = Field(default_factory=RuntimeConfig)
    arms: Dict[str, ArmConfig] = Field(default_factory=dict)
    cameras: Dict[str, CameraConfig] = Field(default_factory=dict)
    power: PowerConfig = Field(default_factory=PowerConfig)
    recording: RecordingConfig = Field(default_factory=RecordingConfig)
    export: ExportConfig = Field(default_factory=ExportConfig)
    inputs: List[InputDeviceConfig] = Field(default_factory=list)

    # Not part of YAML: where the config was loaded from.
    config_path: Optional[str] = None

    @model_validator(mode="after")
    def _check(self) -> "StationConfig":
        for side in self.arms:
            if side not in SIDES:
                raise ValueError(f"arm names must be 'left'/'right', got {side!r}")
        ids = [c.id for c in self.power.channels]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate power channel ids")
        for side, arm in self.arms.items():
            for key in ("power_channel", "leader_power_channel"):
                ch = getattr(arm, key)
                if ch and ch not in ids:
                    raise ValueError(f"arms.{side}.{key} {ch!r} not in power.channels")
        return self

    # ------------------------------------------------------------------ paths

    @property
    def base_dir(self) -> Path:
        if not self.config_path:
            return Path.cwd()
        parent = Path(self.config_path).resolve().parent
        return parent.parent if parent.name == "config" else parent

    @property
    def data_root(self) -> Path:
        p = Path(os.path.expanduser(self.station.data_root))
        return p if p.is_absolute() else (self.base_dir / p)

    def resolve(self, path: str) -> Path:
        """Resolve a repo-relative path (e.g. calibration files) against the project root."""
        p = Path(os.path.expanduser(path))
        return p if p.is_absolute() else (self.base_dir / p)

    def cal_path(self, path: str) -> Path:
        """Calibration files belong to the physical station, so relative paths live under data_root."""
        p = Path(os.path.expanduser(path))
        return p if p.is_absolute() else (self.data_root / p)

    def enabled_arms(self) -> List[str]:
        return [s for s in SIDES if s in self.arms and self.arms[s].enabled]


def load_config(path: str | os.PathLike, force_sim: bool = False) -> StationConfig:
    path = Path(path)
    with open(path) as f:
        raw = yaml.safe_load(f) or {}
    cfg = StationConfig.model_validate(raw)
    cfg.config_path = str(path.resolve())
    if force_sim:
        make_sim(cfg)
    return cfg


def make_sim(cfg: StationConfig) -> None:
    """Switch every device to its simulated twin (keeps names, channels, rates)."""
    cfg.station.sim = True
    for arm in cfg.arms.values():
        arm.follower.backend = "sim"
        arm.leader.backend = "sim"
        if arm.trigger.backend != "none":
            arm.trigger.backend = "sim"
        if arm.fingertips.backend != "none":
            arm.fingertips.backend = "sim"
    for cam in cfg.cameras.values():
        cam.backend = "sim"
    if cfg.power.channels:
        cfg.power.backend = "sim"
        if cfg.power.estop_input is None:
            cfg.power.estop_input = 0
