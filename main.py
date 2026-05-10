"""
main.py — StudySync API
Optimistic Locking fix for the Lost Update problem.
Student ID: bscs23214
"""

import sqlite3
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from optimistic_lock import OptimisticLock, VersionConflictError

# ── Config ────────────────────────────────────────────────────────────────────
STUDENT_ID = "bscs23214"
DB_PATH    = Path(__file__).parent / "studysync.db"

# ── Database ──────────────────────────────────────────────────────────────────
_local = threading.local()


def get_conn() -> sqlite3.Connection:
    if not hasattr(_local, "conn") or _local.conn is None:
        _local.conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        _local.conn.row_factory = sqlite3.Row
        _local.conn.execute("PRAGMA journal_mode=WAL")
    return _local.conn


def init_db():
    conn = get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS documents (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            title      TEXT    NOT NULL,
            body       TEXT    NOT NULL DEFAULT '',
            version    INTEGER NOT NULL DEFAULT 1,
            owner      TEXT    NOT NULL DEFAULT 'anonymous',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        INSERT OR IGNORE INTO documents (id, title, body, version, owner)
        VALUES (1, 'Distributed Systems Notes', 'Initial content.', 1, 'alice');
    """)
    conn.commit()


# ── Middleware: X-Student-ID header on every response ─────────────────────────
class StudentIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Student-ID"] = STUDENT_ID
        return response


# ── App setup ─────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(
    title="StudySync API",
    description="Optimistic Locking — Lost Update fix",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(CORSMiddleware, allow_origins=["*"],
                   allow_methods=["*"], allow_headers=["*"])
app.add_middleware(StudentIDMiddleware)


# ── Pydantic models ────────────────────────────────────────────────────────────
class DocumentCreate(BaseModel):
    title: str
    body: str = ""
    owner: str = "anonymous"


class DocumentUpdate(BaseModel):
    body: str
    version: int          # client MUST send the version it last read
    title: str | None = None


# ── Routes ─────────────────────────────────────────────────────────────────────
@app.get("/", tags=["health"])
async def root():
    return {"status": "ok", "student_id": STUDENT_ID}


@app.get("/health", tags=["health"])
async def health():
    lock = OptimisticLock(get_conn())
    return {"status": "ok", "student_id": STUDENT_ID,
            "optimistic_lock": lock.status()}


@app.get("/documents", tags=["documents"])
async def list_documents():
    conn = get_conn()
    rows = conn.execute(
        "SELECT id, title, body, version, owner, created_at, updated_at "
        "FROM documents ORDER BY id"
    ).fetchall()
    return [dict(r) for r in rows]


@app.post("/documents", status_code=201, tags=["documents"])
async def create_document(payload: DocumentCreate):
    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO documents (title, body, owner) VALUES (?, ?, ?)",
        (payload.title, payload.body, payload.owner),
    )
    conn.commit()
    row = conn.execute(
        "SELECT id, title, body, version, owner, created_at, updated_at "
        "FROM documents WHERE id = ?", (cur.lastrowid,)
    ).fetchone()
    return dict(row)


@app.get("/documents/{doc_id}", tags=["documents"])
async def get_document(doc_id: int):
    conn = get_conn()
    row = conn.execute(
        "SELECT id, title, body, version, owner, created_at, updated_at "
        "FROM documents WHERE id = ?", (doc_id,)
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Document not found")
    return dict(row)


@app.put("/documents/{doc_id}", tags=["documents"])
async def update_document(doc_id: int, payload: DocumentUpdate):
    """
    Optimistic Locking — the core route.
    Client sends the version it last saw. If stale → 409 Conflict.
    """
    lock = OptimisticLock(get_conn())
    try:
        updated = lock.save(
            doc_id=doc_id,
            body=payload.body,
            client_version=payload.version,
            title=payload.title,
        )
        return updated
    except VersionConflictError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error":           "version_conflict",
                "message":         str(e),
                "current_version": e.current_version,
                "your_version":    e.your_version,
            },
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.delete("/documents/{doc_id}", status_code=204, tags=["documents"])
async def delete_document(doc_id: int):
    conn = get_conn()
    cur = conn.execute("DELETE FROM documents WHERE id = ?", (doc_id,))
    conn.commit()
    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail="Document not found")


@app.get("/lock/status", tags=["optimistic-lock"])
async def lock_status():
    """Shows the current optimistic lock pattern info (mirrors /cb/status)."""
    lock = OptimisticLock(get_conn())
    return lock.status()
