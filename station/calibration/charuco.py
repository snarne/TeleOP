"""ChArUco board helpers: board image, detection, intrinsic calibration, overlays,
and synthetic views (so the camera wizard can be exercised in --sim)."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Dict, List

import numpy as np

SQUARES_X, SQUARES_Y = 5, 7
DICT_NAME = "DICT_5X5_100"


def _cv():
    import cv2

    return cv2


def board(square_mm: float = 30.0, marker_mm: float = 22.0):
    cv2 = _cv()
    d = cv2.aruco.getPredefinedDictionary(getattr(cv2.aruco, DICT_NAME))
    return cv2.aruco.CharucoBoard((SQUARES_X, SQUARES_Y), square_mm / 1000.0, marker_mm / 1000.0, d)


def board_png(px_per_mm: float = 300 / 25.4, square_mm: float = 30.0, marker_mm: float = 22.0) -> bytes:
    """Printable board (300 dpi at 100% scale) with a quiet zone and a 50 mm scale bar."""
    cv2 = _cv()
    b = board(square_mm, marker_mm)
    w = int(SQUARES_X * square_mm * px_per_mm)
    h = int(SQUARES_Y * square_mm * px_per_mm)
    img = b.generateImage((w, h), marginSize=0)
    margin = int(15 * px_per_mm)
    canvas = np.full((h + 2 * margin + int(18 * px_per_mm), w + 2 * margin), 255, np.uint8)
    canvas[margin:margin + h, margin:margin + w] = img
    y = margin + h + int(8 * px_per_mm)
    x0 = margin
    cv2.line(canvas, (x0, y), (x0 + int(50 * px_per_mm), y), 0, 4)
    cv2.putText(canvas, f"50 mm  |  ChArUco {SQUARES_X}x{SQUARES_Y} {DICT_NAME} square {square_mm:g} mm marker {marker_mm:g} mm",
                (x0, y + int(7 * px_per_mm)), cv2.FONT_HERSHEY_SIMPLEX, 1.2, 0, 2, cv2.LINE_AA)
    ok, png = cv2.imencode(".png", canvas)
    return png.tobytes()


def _detect_gray(gray, square_mm: float, marker_mm: float):
    cv2 = _cv()
    b = board(square_mm, marker_mm)
    det = cv2.aruco.CharucoDetector(b)
    corners, ids, mcorners, mids = det.detectBoard(gray)
    return b, corners, ids, mcorners, mids


def detect(path: Path, square_mm: float, marker_mm: float) -> Dict:
    cv2 = _cv()
    img = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    if img is None:
        raise FileNotFoundError(path)
    _, corners, ids, _, _ = _detect_gray(img, square_mm, marker_mm)
    n = 0 if ids is None else len(ids)
    return {"n": n, "size": (img.shape[1], img.shape[0])}


def calibrate(paths: List[Path], square_mm: float, marker_mm: float) -> Dict:
    cv2 = _cv()
    obj_all, img_all, size = [], [], None
    for p in paths:
        gray = cv2.imread(str(p), cv2.IMREAD_GRAYSCALE)
        size = (gray.shape[1], gray.shape[0])
        b, corners, ids, _, _ = _detect_gray(gray, square_mm, marker_mm)
        if ids is None or len(ids) < 8:
            continue
        obj, img = b.matchImagePoints(corners, ids)
        obj_all.append(obj)
        img_all.append(img)
    if len(obj_all) < 6:
        raise ValueError("too few usable views")
    rms, K, D, rvecs, tvecs = cv2.calibrateCamera(obj_all, img_all, size, None, None)
    per_view = []
    for o, i, r, t in zip(obj_all, img_all, rvecs, tvecs):
        proj, _ = cv2.projectPoints(o, r, t, K, D)
        per_view.append(float(np.sqrt(np.mean(np.sum((proj.reshape(-1, 2) - i.reshape(-1, 2)) ** 2, axis=1)))))
    return {"rms": float(rms), "image_size": list(size), "camera_matrix": K.tolist(),
            "dist_coeffs": D.reshape(-1).tolist(), "views": len(obj_all),
            "per_view_rms": [round(x, 4) for x in per_view],
            "fov_deg": [round(math.degrees(2 * math.atan(size[0] / (2 * K[0, 0]))), 2),
                        round(math.degrees(2 * math.atan(size[1] / (2 * K[1, 1]))), 2)]}


def overlay_jpeg(jpeg: bytes, square_mm: float = 30.0, marker_mm: float = 22.0) -> bytes:
    cv2 = _cv()
    img = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        return jpeg
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    _, corners, ids, mcorners, mids = _detect_gray(gray, square_mm, marker_mm)
    if mids is not None and len(mids):
        cv2.aruco.drawDetectedMarkers(img, mcorners, mids)
    if ids is not None and len(ids):
        cv2.aruco.drawDetectedCornersCharuco(img, corners, ids, (0, 255, 0))
    n = 0 if ids is None else len(ids)
    cv2.putText(img, f"corners: {n}", (12, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0) if n >= 8 else (0, 0, 255),
                2, cv2.LINE_AA)
    ok, out = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
    return out.tobytes()


def render_synthetic_view(path: Path, i: int, square_mm: float, marker_mm: float, size=(640, 480)) -> None:
    """Project the board through a known pinhole camera at a pseudo-random pose."""
    cv2 = _cv()
    rng = np.random.default_rng(1000 + i)
    K = np.array([[610.0, 0, 322.0], [0, 612.0, 241.0], [0, 0, 1]])
    D = np.array([0.08, -0.12, 0.0, 0.0, 0.0])
    b = board(square_mm, marker_mm)
    ppm = 4.0  # px per mm on the source texture
    W, H = int(SQUARES_X * square_mm * ppm), int(SQUARES_Y * square_mm * ppm)
    tex = b.generateImage((W, H), marginSize=0)
    tex = cv2.copyMakeBorder(tex, 40, 40, 40, 40, cv2.BORDER_CONSTANT, value=255)
    bw, bh = SQUARES_X * square_mm / 1000.0, SQUARES_Y * square_mm / 1000.0
    rvec = np.array([rng.uniform(-0.6, 0.6), rng.uniform(-0.6, 0.6), rng.uniform(-0.4, 0.4)])
    tvec = np.array([rng.uniform(-0.06, 0.06) - bw / 2, rng.uniform(-0.05, 0.05) - bh / 2, rng.uniform(0.32, 0.55)])
    m = 40 / ppm / 1000.0
    obj = np.array([[-m, -m, 0], [bw + m, -m, 0], [bw + m, bh + m, 0], [-m, bh + m, 0]], np.float64)
    img_pts, _ = cv2.projectPoints(obj, rvec, tvec, K, np.zeros(5))
    src = np.array([[0, 0], [tex.shape[1], 0], [tex.shape[1], tex.shape[0]], [0, tex.shape[0]]], np.float32)
    Hm = cv2.getPerspectiveTransform(src, img_pts.reshape(-1, 2).astype(np.float32))
    bg = np.full((size[1], size[0]), 90, np.uint8)
    warped = cv2.warpPerspective(tex, Hm, size, borderMode=cv2.BORDER_CONSTANT, borderValue=0)
    mask = cv2.warpPerspective(np.full_like(tex, 255), Hm, size, borderMode=cv2.BORDER_CONSTANT, borderValue=0)
    out = np.where(mask > 0, warped, bg).astype(np.uint8)
    # apply lens distortion by remapping (inverse map via undistort points grid)
    mapx, mapy = cv2.initUndistortRectifyMap(K, -D, None, K, size, cv2.CV_32FC1)
    out = cv2.remap(out, mapx, mapy, cv2.INTER_LINEAR)
    out = cv2.GaussianBlur(out, (3, 3), 0.6)
    noise = rng.normal(0, 2.0, out.shape)
    out = np.clip(out.astype(np.float64) + noise, 0, 255).astype(np.uint8)
    path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(path), out)
