"""HTTP + WebSocket API (contract: docs/architecture.md → API contract)."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import Body, FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlmodel import func, select

from station.calibration import charuco
from station.calibration.generator import generate_script
from station.db import Department, Episode, Task, User, UserDepartment, slugify
from station.orchestrator import Orchestrator, StationError
from station.recording.raw_episode import decimate_series, load_episode

ROOT = Path(__file__).resolve().parent.parent
UI_DIST = ROOT / "ui" / "dist"
STATIC = Path(__file__).resolve().parent / "static"


# ----------------------------------------------------------------------------- bodies


class SessionBody(BaseModel):
    operator_id: Optional[int] = None
    department_id: Optional[int] = None
    task_id: Optional[int] = None


class DepartmentBody(BaseModel):
    name: Optional[str] = None
    color: Optional[str] = None
    description: Optional[str] = None


class UserBody(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    role: Optional[str] = None
    active: Optional[bool] = None
    department_ids: Optional[List[int]] = None


class TaskBody(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    department_id: Optional[int] = None


class PowerBody(BaseModel):
    channel: str = "all"
    on: bool = True


class PowerCycleBody(BaseModel):
    channel: str = "all"
    off_s: float = 3.0


class ArmsBody(BaseModel):
    arms: Optional[List[str]] = None


class TeleopBody(BaseModel):
    enabled: bool


class SaveBody(BaseModel):
    success: Optional[bool] = None
    notes: str = ""


class EpisodePatch(BaseModel):
    success: Optional[bool] = None
    notes: Optional[str] = None
    tags: Optional[List[str]] = None


class ExportBody(BaseModel):
    episode_ids: List[str]
    name: str
    fps: Optional[int] = None


class StepBody(BaseModel):
    inputs: Dict[str, Any] = Field(default_factory=dict)


class ScriptBody(BaseModel):
    procedure_id: str


class ActionBody(BaseModel):
    action: str


def create_app(orch: Orchestrator) -> FastAPI:
    app = FastAPI(title="Teleop Station", version=orch.version)
    app.state.orch = orch
    db = orch.db

    @app.exception_handler(StationError)
    async def _station_error(_req: Request, exc: StationError):
        return JSONResponse({"detail": exc.detail, "hint": exc.hint}, status_code=exc.status)

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_req: Request, exc: StarletteHTTPException):
        return JSONResponse({"detail": str(exc.detail), "hint": ""}, status_code=exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_req: Request, exc: RequestValidationError):
        errs = exc.errors()
        first = errs[0] if errs else {}
        where = ".".join(str(x) for x in first.get("loc", []) if x != "body")
        return JSONResponse({"detail": f"invalid request: {where} {first.get('msg', '')}".strip(),
                             "hint": "check the request body", "errors": errs}, status_code=422)

    def nf(what: str):
        raise HTTPException(404, detail=f"{what} not found")

    # ------------------------------------------------------------------ station & session

    @app.get("/api/station")
    def station():
        c = orch.cfg
        return {"name": c.station.name, "version": orch.version, "sim": orch.sim, "arms": c.enabled_arms(),
                "cameras": [{"name": n, "label": cc.label or n, "attached_to": cc.attached_to} for n, cc in c.cameras.items()],
                "power_channels": [{"id": p.id, "label": p.label} for p in c.power.channels],
                "data_root": str(orch.data_root), "control_hz": c.runtime.control_hz,
                "triggers": {s: c.arms[s].trigger.backend for s in c.enabled_arms()},
                "grip_force_max": {s: c.arms[s].follower.max_grip_force_n for s in c.enabled_arms()}}

    @app.get("/api/session")
    def get_session():
        return orch.session()

    @app.put("/api/session")
    def put_session(body: SessionBody):
        return orch.set_session(body.model_dump())

    # ------------------------------------------------------------------ organization

    def dept_dict(s, d: Department) -> Dict:
        uc = s.exec(select(func.count()).select_from(UserDepartment).where(UserDepartment.department_id == d.id)).one()
        ec = s.exec(select(func.count()).select_from(Episode).where(Episode.department_id == d.id)).one()
        return {"id": d.id, "name": d.name, "color": d.color, "description": d.description,
                "user_count": int(uc), "episode_count": int(ec)}

    def user_dict(s, u: User) -> Dict:
        ec = s.exec(select(func.count()).select_from(Episode).where(Episode.user_id == u.id)).one()
        return {"id": u.id, "name": u.name, "email": u.email, "role": u.role, "active": u.active,
                "department_ids": db.user_department_ids(s, u.id), "episode_count": int(ec),
                "created_at": u.created_at.isoformat()}

    def task_dict(t: Task) -> Dict:
        return {"id": t.id, "name": t.name, "slug": t.slug, "description": t.description, "department_id": t.department_id}

    @app.get("/api/departments")
    def departments():
        with db.session() as s:
            return [dept_dict(s, d) for d in s.exec(select(Department).order_by(Department.name))]

    @app.post("/api/departments")
    def create_department(body: DepartmentBody):
        if not body.name or not body.name.strip():
            raise StationError("name is required", status=400)
        with db.lock, db.session() as s:
            if s.exec(select(Department).where(Department.name == body.name.strip())).first():
                raise StationError(f"department '{body.name}' already exists", status=409)
            d = Department(name=body.name.strip(), color=body.color or "#4f7cff", description=body.description or "")
            s.add(d)
            s.commit()
            s.refresh(d)
            return dept_dict(s, d)

    @app.patch("/api/departments/{did}")
    def patch_department(did: int, body: DepartmentBody):
        with db.lock, db.session() as s:
            d = s.get(Department, did) or nf("department")
            for k, v in body.model_dump(exclude_none=True).items():
                setattr(d, k, v.strip() if isinstance(v, str) else v)
            s.add(d)
            s.commit()
            s.refresh(d)
            return dept_dict(s, d)

    @app.delete("/api/departments/{did}", status_code=204)
    def delete_department(did: int):
        with db.lock, db.session() as s:
            d = s.get(Department, did) or nf("department")
            if s.exec(select(Episode).where(Episode.department_id == did)).first():
                raise StationError("department has recorded episodes", "rename it instead, or move its episodes first")
            for r in s.exec(select(UserDepartment).where(UserDepartment.department_id == did)):
                s.delete(r)
            for t in s.exec(select(Task).where(Task.department_id == did)):
                t.department_id = None
                s.add(t)
            s.delete(d)
            s.commit()
        return Response(status_code=204)

    @app.get("/api/users")
    def users(include_inactive: bool = False):
        with db.session() as s:
            q = select(User).order_by(User.name)
            if not include_inactive:
                q = q.where(User.active == True)  # noqa: E712
            return [user_dict(s, u) for u in s.exec(q)]

    @app.post("/api/users")
    def create_user(body: UserBody):
        if not body.name or not body.name.strip():
            raise StationError("name is required", status=400)
        with db.lock, db.session() as s:
            u = User(name=body.name.strip(), email=body.email or "", role=body.role or "operator")
            s.add(u)
            s.commit()
            s.refresh(u)
            db.set_user_departments(s, u.id, body.department_ids or [])
            s.commit()
            return user_dict(s, u)

    @app.patch("/api/users/{uid}")
    def patch_user(uid: int, body: UserBody):
        with db.lock, db.session() as s:
            u = s.get(User, uid) or nf("user")
            data = body.model_dump(exclude_none=True)
            depts = data.pop("department_ids", None)
            for k, v in data.items():
                setattr(u, k, v)
            s.add(u)
            if depts is not None:
                db.set_user_departments(s, uid, depts)
            s.commit()
            s.refresh(u)
            return user_dict(s, u)

    @app.get("/api/tasks")
    def tasks(department_id: Optional[int] = None):
        with db.session() as s:
            q = select(Task).order_by(Task.name)
            if department_id is not None:
                q = q.where((Task.department_id == department_id) | (Task.department_id == None))  # noqa: E711
            return [task_dict(t) for t in s.exec(q)]

    @app.post("/api/tasks")
    def create_task(body: TaskBody):
        if not body.name or not body.name.strip():
            raise StationError("name is required", status=400)
        with db.lock, db.session() as s:
            t = Task(name=body.name.strip(), slug=slugify(body.name), description=body.description or "",
                     department_id=body.department_id)
            s.add(t)
            s.commit()
            s.refresh(t)
            return task_dict(t)

    @app.patch("/api/tasks/{tid}")
    def patch_task(tid: int, body: TaskBody):
        with db.lock, db.session() as s:
            t = s.get(Task, tid) or nf("task")
            for k, v in body.model_dump(exclude_unset=True).items():
                setattr(t, k, v)
            if body.name:
                t.slug = slugify(body.name)
            s.add(t)
            s.commit()
            s.refresh(t)
            return task_dict(t)

    @app.delete("/api/tasks/{tid}", status_code=204)
    def delete_task(tid: int):
        with db.lock, db.session() as s:
            t = s.get(Task, tid) or nf("task")
            if s.exec(select(Episode).where(Episode.task_id == tid)).first():
                raise StationError("task has recorded episodes", "rename it instead")
            s.delete(t)
            s.commit()
        return Response(status_code=204)

    # ------------------------------------------------------------------ control

    @app.post("/api/control/power")
    def power(body: PowerBody):
        return orch.set_power(body.channel, body.on)

    @app.post("/api/control/power_cycle")
    def power_cycle(body: PowerCycleBody):
        return orch.power_cycle(body.channel, body.off_s)

    @app.post("/api/control/start_arms")
    def start_arms(body: ArmsBody = Body(default_factory=ArmsBody)):
        return orch.start_arms(body.arms)

    @app.post("/api/control/stop_arms")
    def stop_arms():
        return orch.stop_arms()

    @app.post("/api/control/teleop")
    def teleop(body: TeleopBody):
        return orch.set_teleop(body.enabled)

    @app.post("/api/control/estop")
    def estop():
        return orch.estop()

    @app.post("/api/control/clear_fault")
    def clear_fault():
        return orch.clear_fault()

    @app.post("/api/control/home")
    def home():
        return orch.home()

    @app.post("/api/control/action")
    def action(body: ActionBody):
        return orch.do_action(body.action, source="api")

    # ------------------------------------------------------------------ recording

    @app.post("/api/recording/start")
    def rec_start():
        return orch.start_recording()

    @app.post("/api/recording/save")
    def rec_save(body: SaveBody = Body(default_factory=SaveBody)):
        return orch.save_recording(body.success, body.notes)

    @app.post("/api/recording/abort")
    def rec_abort():
        return orch.abort_recording()

    # ------------------------------------------------------------------ episodes

    @app.get("/api/episodes")
    def episodes(department_id: Optional[int] = None, user_id: Optional[int] = None, task_id: Optional[int] = None,
                 success: Optional[str] = None, q: Optional[str] = None, limit: int = 100, offset: int = 0):
        with db.session() as s:
            stmt = select(Episode)
            if department_id is not None:
                stmt = stmt.where(Episode.department_id == department_id)
            if user_id is not None:
                stmt = stmt.where(Episode.user_id == user_id)
            if task_id is not None:
                stmt = stmt.where(Episode.task_id == task_id)
            if success in ("true", "false"):
                stmt = stmt.where(Episode.success == (success == "true"))
            elif success == "unset":
                stmt = stmt.where(Episode.success == None)  # noqa: E711
            rows = list(s.exec(stmt.order_by(Episode.started_at.desc())))
        items = [orch.episode_dict(e) for e in rows]
        if q:
            ql = q.lower()
            items = [i for i in items if ql in " ".join(str(i.get(k) or "") for k in
                                                        ("id", "user_name", "department_name", "task_name", "notes")).lower()
                     or any(ql in t.lower() for t in i["tags"])]
        return {"items": items[offset: offset + limit], "total": len(items)}

    def get_ep(eid: str) -> Episode:
        with db.session() as s:
            return s.get(Episode, eid) or nf("episode")

    @app.get("/api/episodes/{eid}")
    def episode(eid: str):
        return orch.episode_dict(get_ep(eid))

    @app.patch("/api/episodes/{eid}")
    def patch_episode(eid: str, body: EpisodePatch):
        with db.lock, db.session() as s:
            e = s.get(Episode, eid) or nf("episode")
            data = body.model_dump(exclude_unset=True)
            if "success" in data:
                e.success = data["success"]
            if "notes" in data:
                e.notes = data["notes"] or ""
            if "tags" in data:
                e.tags_json = json.dumps(data["tags"] or [])
            s.add(e)
            s.commit()
            s.refresh(e)
        # keep episode.json in sync so the raw episode stays self-describing
        p = Path(e.path) / "episode.json"
        if p.exists():
            try:
                info = json.loads(p.read_text())
                info.update({"success": e.success, "notes": e.notes, "tags": json.loads(e.tags_json)})
                p.write_text(json.dumps(info, indent=2))
            except Exception:
                pass
        return orch.episode_dict(e)

    @app.delete("/api/episodes/{eid}", status_code=204)
    def delete_episode(eid: str):
        with db.lock, db.session() as s:
            e = s.get(Episode, eid) or nf("episode")
            path = e.path
            s.delete(e)
            s.commit()
        if path and os.path.isdir(path) and str(orch.data_root) in str(Path(path).resolve()):
            trash = orch.data_root / "recordings" / ".trash" / Path(path).name
            trash.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(path, trash)  # recoverable until the trash is emptied
        return Response(status_code=204)

    @app.get("/api/episodes/{eid}/video/{camera}")
    def episode_video(eid: str, camera: str):
        e = get_ep(eid)
        p = Path(e.path) / "cameras" / f"{camera}.mp4"
        if not p.exists():
            nf("video")
        return FileResponse(p, media_type="video/mp4")

    @app.get("/api/episodes/{eid}/telemetry")
    def episode_telemetry(eid: str, max_points: int = 1500):
        e = get_ep(eid)
        if not os.path.isdir(e.path):
            nf("episode files")
        return decimate_series(load_episode(Path(e.path)), max_points)

    @app.post("/api/exports")
    def create_export(body: ExportBody):
        return orch.create_export(body.episode_ids, body.name, body.fps)

    @app.get("/api/jobs")
    def jobs():
        return sorted(orch.jobs.values(), key=lambda j: -j["created_at"])

    @app.get("/api/jobs/{jid}")
    def job(jid: str):
        return orch.jobs.get(jid) or nf("job")

    # ------------------------------------------------------------------ calibration

    @app.get("/api/calibration")
    def calibration():
        return {"items": orch.calibration_items()}

    @app.get("/api/calibration/procedures")
    def procedures():
        return [p.describe() for p in orch.procedures.values()]

    @app.post("/api/calibration/procedures/{pid}/start")
    def cal_start(pid: str):
        return orch.cal_start(pid)

    @app.post("/api/calibration/procedures/{pid}/steps/{sid}")
    def cal_step(pid: str, sid: str, body: StepBody = Body(default_factory=StepBody)):
        return orch.cal_step(pid, sid, body.inputs)

    @app.post("/api/calibration/procedures/{pid}/commit")
    def cal_commit(pid: str):
        return orch.cal_commit(pid)

    @app.post("/api/calibration/procedures/{pid}/cancel")
    def cal_cancel(pid: str):
        return orch.cal_cancel(pid)

    @app.post("/api/calibration/scripts")
    def cal_script(body: ScriptBody):
        try:
            return generate_script(orch.cfg, body.procedure_id, orch.data_root / "calibration" / "scripts")
        except KeyError as e:
            raise StationError(str(e), status=404)

    @app.get("/api/calibration/files/{item_id}", response_class=PlainTextResponse)
    def cal_file(item_id: str):
        try:
            p = orch.cal_file(item_id)
        except (KeyError, ValueError):
            nf("calibration item")
        if not p.exists():
            nf("calibration file")
        return p.read_text()

    @app.get("/api/calibration/charuco.png")
    def charuco_png(square_mm: float = 30.0, marker_mm: float = 22.0):
        return Response(charuco.board_png(square_mm=square_mm, marker_mm=marker_mm), media_type="image/png",
                        headers={"Content-Disposition": 'attachment; filename="charuco_5x7.png"'})

    # ------------------------------------------------------------------ health / logs / hardware

    @app.get("/api/health")
    def health():
        return orch.health()

    @app.post("/api/health/run")
    def health_run():
        return orch.health(rerun=True)

    @app.get("/api/logs")
    def logs(limit: int = 500, level: Optional[str] = None, source: Optional[str] = None):
        return orch.logbus.recent(limit, level, source)

    @app.post("/api/hardware/can/reset")
    def can_reset():
        return orch.reset_can()

    @app.post("/api/hardware/arms/{side}/reconnect")
    def reconnect(side: str):
        return orch.reconnect_arm(side)

    @app.post("/api/hardware/dxl/{side}/scan")
    def dxl_scan(side: str):
        return orch.arm_request(side, "scan", timeout=15)

    # ------------------------------------------------------------------ cameras

    @app.get("/api/cameras/{name}/snapshot.jpg")
    def snapshot(name: str, overlay: Optional[str] = None):
        slot = orch.jpegs.get(name) or nf("camera")
        _, data = slot.get()
        if not data:
            raise StationError(f"camera {name} has no frame yet", "check the camera is connected", status=503)
        if overlay == "charuco":
            p = orch.active_cal
            sq, mk = (getattr(p, "square_mm", 30.0), getattr(p, "marker_mm", 22.0)) if p else (30.0, 22.0)
            data = charuco.overlay_jpeg(data, sq, mk)
        return Response(data, media_type="image/jpeg", headers={"Cache-Control": "no-store"})

    @app.get("/api/cameras/{name}/stream.mjpg")
    async def stream(name: str, request: Request):
        slot = orch.jpegs.get(name) or nf("camera")
        period = 1.0 / max(orch.cfg.recording.preview_fps, 1)

        async def gen():
            last = -1
            while True:
                if await request.is_disconnected():
                    break
                seq, data = slot.get()
                if data and seq != last:
                    last = seq
                    yield (b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: " + str(len(data)).encode()
                           + b"\r\n\r\n" + data + b"\r\n")
                await asyncio.sleep(period / 2)

        return StreamingResponse(gen(), media_type="multipart/x-mixed-replace; boundary=frame",
                                 headers={"Cache-Control": "no-store"})

    # ------------------------------------------------------------------ settings

    @app.get("/api/settings")
    def get_settings():
        return orch.settings()

    @app.put("/api/settings")
    def put_settings(body: Dict[str, Any] = Body(...)):
        return orch.update_settings(body)

    # ------------------------------------------------------------------ websockets

    @app.websocket("/ws/state")
    async def ws_state(ws: WebSocket):
        await ws.accept()
        period = 1.0 / max(orch.cfg.runtime.state_hz, 1)
        try:
            while True:
                snap = await asyncio.get_running_loop().run_in_executor(None, orch.snapshot)
                await ws.send_text(json.dumps(snap, default=str))
                await asyncio.sleep(period)
        except (WebSocketDisconnect, RuntimeError):
            pass

    @app.websocket("/ws/logs")
    async def ws_logs(ws: WebSocket):
        await ws.accept()
        q = orch.logbus.subscribe()
        try:
            for line in orch.logbus.recent(200):
                await ws.send_text(json.dumps(line))
            while True:
                line = await q.get()
                await ws.send_text(json.dumps(line))
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            orch.logbus.unsubscribe(q)

    # ------------------------------------------------------------------ static UI

    if STATIC.exists():
        app.mount("/static", StaticFiles(directory=STATIC), name="static")
    if UI_DIST.exists():
        app.mount("/assets", StaticFiles(directory=UI_DIST / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str):
            f = UI_DIST / path
            if path and f.is_file() and UI_DIST in f.resolve().parents:
                return FileResponse(f)
            return FileResponse(UI_DIST / "index.html")
    else:
        @app.get("/", include_in_schema=False)
        def no_ui():
            return PlainTextResponse("Teleop Station API is running. Build the UI: cd ui && npm install && npm run build")

    return app
