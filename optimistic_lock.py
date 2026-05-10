"""
optimistic_lock.py
──────────────────
The Optimistic Locking pattern — reusable helper.

How it works:
  Every document has a version number (starts at 1).
  When a user loads a document they receive the current version.
  When they save, they send back the version they saw.
  The database UPDATE is guarded by:

      WHERE id = ? AND version = ?

  If the version still matches  → save succeeds, version goes up by 1.
  If someone else already saved → 0 rows updated → VersionConflictError raised.
  The caller must re-fetch the document, merge changes, and retry.

Student ID: bscs23214
"""


class VersionConflictError(Exception):
    """Raised when an optimistic lock check fails."""

    def __init__(self, doc_id: int, your_version: int, current_version: int):
        self.doc_id = doc_id
        self.your_version = your_version
        self.current_version = current_version
        super().__init__(
            f"Document {doc_id}: your version ({your_version}) is stale. "
            f"Current version is {current_version}. "
            f"Re-fetch, merge your changes, and retry."
        )


class OptimisticLock:
    """
    Helper that wraps a SQLite connection and provides
    version-guarded save operations.

    Usage:
        lock = OptimisticLock(conn)
        lock.save(doc_id=1, body="new text", client_version=1)
        # raises VersionConflictError if version 1 is no longer current
    """

    def __init__(self, conn):
        self._conn = conn

    def save(self, doc_id: int, body: str, client_version: int,
             title: str | None = None) -> dict:
        """
        Attempt to save a document.

        Returns the updated document dict on success.
        Raises VersionConflictError if the client_version is stale.
        Raises ValueError if the document does not exist.
        """
        if title:
            sql = (
                "UPDATE documents "
                "SET body = ?, title = ?, version = version + 1, "
                "    updated_at = CURRENT_TIMESTAMP "
                "WHERE id = ? AND version = ?"
            )
            params = (body, title, doc_id, client_version)
        else:
            sql = (
                "UPDATE documents "
                "SET body = ?, version = version + 1, "
                "    updated_at = CURRENT_TIMESTAMP "
                "WHERE id = ? AND version = ?"
            )
            params = (body, doc_id, client_version)

        cur = self._conn.execute(sql, params)
        self._conn.commit()

        if cur.rowcount == 0:
            # Check if the document exists at all
            row = self._conn.execute(
                "SELECT id, version FROM documents WHERE id = ?", (doc_id,)
            ).fetchone()

            if not row:
                raise ValueError(f"Document {doc_id} does not exist.")

            raise VersionConflictError(
                doc_id=doc_id,
                your_version=client_version,
                current_version=row["version"],
            )

        # Return the saved document
        row = self._conn.execute(
            "SELECT id, title, body, version, owner, created_at, updated_at "
            "FROM documents WHERE id = ?", (doc_id,)
        ).fetchone()
        return dict(row)

    def status(self) -> dict:
        """Return a summary (mirrors circuit_breaker.status() style)."""
        return {
            "pattern": "Optimistic Locking",
            "mechanism": "version column + WHERE version = ? guard",
            "conflict_response": "HTTP 409 Conflict",
        }
