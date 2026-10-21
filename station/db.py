"""Station database (SQLite): organization, people, tasks, episodes, calibration history,
settings. There are no passwords; access control is physical access to the station PC."""

from __future__ import annotations

import json
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from sqlalchemy import event
from sqlmodel import Field, Session, SQLModel, create_engine, select


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def slugify(s: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", s.strip().lower()).strip("-")
    return s or "untitled"


class Department(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True, unique=True)
    color: str = "#4f7cff"
    description: str = ""
    created_at: datetime = Field(default_factory=utcnow)


class User(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    email: str = ""
    role: str = "operator"  # operator | admin
    active: bool = True
    created_at: datetime = Field(default_factory=utcnow)


class UserDepartment(SQLModel, table=True):
    user_id: int = Field(foreign_key="user.id", primary_key=True)
    department_id: int = Field(foreign_key="department.id", primary_key=True)


class Task(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    slug: str = Field(index=True)
    description: str = ""
    department_id: Optional[int] = Field(default=None, foreign_key="department.id")
    created_at: datetime = Field(default_factory=utcnow)


class Episode(SQLModel, table=True):
    id: str = Field(primary_key=True)
    user_id: Optional[int] = Field(default=None, foreign_key="user.id", index=True)
    department_id: Optional[int] = Field(default=None, foreign_key="department.id", index=True)
    task_id: Optional[int] = Field(default=None, foreign_key="task.id", index=True)
    started_at: datetime = Field(default_factory=utcnow, index=True)
    duration_s: float = 0.0
    frames: int = 0
    cameras_json: str = "[]"
    size_mb: float = 0.0
    success: Optional[bool] = None
    notes: str = ""
    tags_json: str = "[]"
    path: str = ""
    status: str = "saved"  # saved | exported | missing
    station: str = ""


class CalibrationRecord(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    item_id: str = Field(index=True)
    created_at: datetime = Field(default_factory=utcnow)
    user_id: Optional[int] = Field(default=None, foreign_key="user.id")
    summary: str = ""
    path: str = ""
    data_json: str = "{}"


class KV(SQLModel, table=True):
    key: str = Field(primary_key=True)
    value_json: str = "null"


class Database:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.engine = create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False})

        @event.listens_for(self.engine, "connect")
        def _pragmas(dbapi_conn, _rec):  # pragma: no cover - trivial
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA foreign_keys=ON")
            cur.close()

        SQLModel.metadata.create_all(self.engine)
        self.lock = threading.RLock()

    def session(self) -> Session:
        return Session(self.engine, expire_on_commit=False)

    # ----------------------------------------------------------------- kv

    def get_kv(self, key: str, default: Any = None) -> Any:
        with self.session() as s:
            row = s.get(KV, key)
            return json.loads(row.value_json) if row else default

    def set_kv(self, key: str, value: Any) -> None:
        with self.lock, self.session() as s:
            row = s.get(KV, key) or KV(key=key)
            row.value_json = json.dumps(value)
            s.add(row)
            s.commit()

    # ----------------------------------------------------------------- org helpers

    def user_department_ids(self, s: Session, user_id: int) -> List[int]:
        return [r.department_id for r in s.exec(select(UserDepartment).where(UserDepartment.user_id == user_id))]

    def set_user_departments(self, s: Session, user_id: int, dept_ids: List[int]) -> None:
        for r in s.exec(select(UserDepartment).where(UserDepartment.user_id == user_id)):
            s.delete(r)
        for d in dict.fromkeys(dept_ids):
            s.add(UserDepartment(user_id=user_id, department_id=d))

    def seed_if_empty(self) -> None:
        """First run: a starter org so the station is usable immediately (rename in Organization)."""
        with self.lock, self.session() as s:
            if s.exec(select(Department)).first() is not None:
                return
            d = Department(name="Manipulation", color="#4f7cff", description="Default department, rename me")
            s.add(d)
            s.commit()
            s.refresh(d)
            u = User(name="Station Admin", role="admin")
            s.add(u)
            s.commit()
            s.refresh(u)
            s.add(UserDepartment(user_id=u.id, department_id=d.id))
            s.add(Task(name="Pick and place", slug="pick-and-place", description="Pick up the object and place it in the bin",
                       department_id=d.id))
            s.commit()
