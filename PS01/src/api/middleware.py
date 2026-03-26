# src/api/middleware.py
import sqlite3
from datetime import datetime, UTC
from functools import wraps
from fastapi import HTTPException, Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse


class ConsentDB:
    def __init__(self, db_path: str = "consent.db"):
        self.db_path = db_path
        self._init_table()

    def _init_table(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS consent (
                    session_id TEXT PRIMARY KEY,
                    customer_id TEXT,
                    scope TEXT,
                    timestamp TEXT,
                    signature_method TEXT
                )
            """)
            # Add bank_id column if it doesn't exist yet (idempotent migration).
            existing = {
                row[1]
                for row in conn.execute("PRAGMA table_info(consent)").fetchall()
            }
            if "bank_id" not in existing:
                conn.execute(
                    "ALTER TABLE consent ADD COLUMN bank_id TEXT NOT NULL DEFAULT ''"
                )
            conn.commit()

    def record_consent(
        self,
        session_id: str,
        customer_id: str,
        scope: str,
        sig_method: str,
        bank_id: str = "",
    ):
        """Store consent record."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO consent
                    (session_id, customer_id, scope, timestamp, signature_method, bank_id)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    customer_id,
                    scope,
                    datetime.now(UTC).isoformat(),
                    sig_method,
                    bank_id,
                ),
            )
            conn.commit()

    def verify_consent(self, session_id: str, scope: str, bank_id: str = "") -> bool:
        """Check if consent exists for scope, optionally filtered by bank_id."""
        with sqlite3.connect(self.db_path) as conn:
            if bank_id:
                row = conn.execute(
                    "SELECT * FROM consent WHERE session_id = ? AND scope = ? AND bank_id = ?",
                    (session_id, scope, bank_id),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT * FROM consent WHERE session_id = ? AND scope = ?",
                    (session_id, scope),
                ).fetchone()
            return row is not None


consent_db = ConsentDB()


def require_consent(scope: str):
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, session_id: str, **kwargs):
            bank_id = kwargs.get("bank_id", "")
            # Also try to pull bank_id from request.state if a Request object is present
            if not bank_id:
                for arg in args:
                    tenant = getattr(getattr(arg, "state", None), "tenant", None)
                    if tenant is not None:
                        bank_id = getattr(tenant, "bank_id", "") or ""
                        break
            if not consent_db.verify_consent(session_id, scope, bank_id=bank_id):
                raise HTTPException(status_code=403, detail="consent required")
            return await func(*args, session_id=session_id, **kwargs)
        return wrapper
    return decorator


class ConsentMiddleware(BaseHTTPMiddleware):
    """
    FastAPI middleware to enforce consent checking on protected routes.
    Exempt demo routes from consent requirement.
    """
    
    EXEMPT_PATHS = {
        "/health",
        "/docs",
        "/openapi.json",
        "/redoc",
    }
    
    async def dispatch(self, request: Request, call_next):
        # Exempt health checks and API docs
        if request.url.path in self.EXEMPT_PATHS or request.url.path.startswith("/demo"):
            return await call_next(request)
        
        # For protected routes, consent checking would be enforced by @require_consent decorator
        # on individual endpoints. This middleware just sets up the context.
        response = await call_next(request)
        return response
