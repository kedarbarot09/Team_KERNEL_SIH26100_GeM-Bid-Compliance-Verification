"""Shared SQLite Database Layer for Bidder Documents & Officer Audit Logs.

Manages persistence for:
1. `documents`: Bidder document uploads, categories, filepaths, and lifecycle status.
2. `audit_log`: Officer verification decisions, flags, justification logs, and timestamps.
"""

from datetime import datetime
import logging
import os
from pathlib import Path
import re
import sqlite3
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Base paths
APP_DIR = Path(__file__).resolve().parent.parent
DB_PATH = APP_DIR / "bidder_documents.db"
UPLOADS_BASE_DIR = APP_DIR / "uploads"


def get_db_path() -> Path:
    """Return the absolute path to the shared SQLite database."""
    return DB_PATH


def get_connection() -> sqlite3.Connection:
    """Obtain a thread-safe connection to the SQLite database with row factory."""
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Initialize SQLite database tables and indexes if they do not exist."""
    conn = get_connection()
    try:
        with conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS documents (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    bidder_id TEXT NOT NULL,
                    category TEXT NOT NULL,
                    document_type TEXT NOT NULL,
                    filename TEXT NOT NULL,
                    filepath TEXT NOT NULL,
                    uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    status TEXT DEFAULT 'pending'
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_docs_bidder ON documents (bidder_id)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_docs_status ON documents (status)
                """
            )

            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS audit_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    bidder_id TEXT NOT NULL,
                    officer_action TEXT NOT NULL,
                    justification TEXT NOT NULL,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_audit_bidder ON audit_log (bidder_id)
                """
            )
        logger.info("Initialized shared SQLite database at %s", DB_PATH)
    finally:
        conn.close()


def sanitize_folder_name(name: str) -> str:
    """Sanitize directory names for safe path operations."""
    return re.sub(r"[^\w\-_]", "_", name.strip())


def save_uploaded_document(
    bidder_id: str,
    category: str,
    document_type: str,
    filename: str,
    file_bytes: bytes,
) -> Dict[str, Any]:
    """Save an uploaded document to disk and record its metadata in SQLite.

    Files are stored under: uploads/{bidder_id}/{sanitized_category}/{filename}
    If a document for this bidder_id and document_type already exists, its record is updated.
    """
    init_db()

    clean_bidder = sanitize_folder_name(bidder_id)
    clean_cat = sanitize_folder_name(category)
    safe_filename = Path(filename).name

    dest_dir = UPLOADS_BASE_DIR / clean_bidder / clean_cat
    dest_dir.mkdir(parents=True, exist_ok=True)
    target_filepath = dest_dir / safe_filename

    # Write file bytes to disk
    with open(target_filepath, "wb") as f:
        f.write(file_bytes)

    now_iso = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = get_connection()
    try:
        with conn:
            # Check if an existing row exists for (bidder_id, document_type)
            cursor = conn.execute(
                """
                SELECT id FROM documents
                WHERE bidder_id = ? AND document_type = ?
                """,
                (bidder_id.strip(), document_type.strip()),
            )
            row = cursor.fetchone()
            if row:
                doc_id = row["id"]
                conn.execute(
                    """
                    UPDATE documents
                    SET category = ?, filename = ?, filepath = ?, uploaded_at = ?, status = 'pending'
                    WHERE id = ?
                    """,
                    (category, safe_filename, str(target_filepath), now_iso, doc_id),
                )
            else:
                cursor = conn.execute(
                    """
                    INSERT INTO documents (bidder_id, category, document_type, filename, filepath, uploaded_at, status)
                    VALUES (?, ?, ?, ?, ?, ?, 'pending')
                    """,
                    (bidder_id.strip(), category, document_type.strip(), safe_filename, str(target_filepath), now_iso),
                )
                doc_id = cursor.lastrowid

        return {
            "id": doc_id,
            "bidder_id": bidder_id.strip(),
            "category": category,
            "document_type": document_type.strip(),
            "filename": safe_filename,
            "filepath": str(target_filepath),
            "uploaded_at": now_iso,
            "status": "pending",
        }
    finally:
        conn.close()


def get_documents_by_bidder(bidder_id: str) -> List[Dict[str, Any]]:
    """Retrieve all uploaded documents for a given bidder ID."""
    init_db()
    conn = get_connection()
    try:
        cursor = conn.execute(
            """
            SELECT id, bidder_id, category, document_type, filename, filepath, uploaded_at, status
            FROM documents
            WHERE bidder_id = ?
            ORDER BY id ASC
            """,
            (bidder_id.strip(),),
        )
        return [dict(r) for r in cursor.fetchall()]
    finally:
        conn.close()


def submit_bidder_documents(bidder_id: str) -> int:
    """Transition all documents for a bidder from 'pending' to 'submitted'."""
    init_db()
    conn = get_connection()
    try:
        with conn:
            cursor = conn.execute(
                """
                UPDATE documents
                SET status = 'submitted'
                WHERE bidder_id = ?
                """,
                (bidder_id.strip(),),
            )
            return cursor.rowcount
    finally:
        conn.close()


def get_submitted_bidders() -> List[Dict[str, Any]]:
    """Retrieve distinct bidders that have submissions, along with doc counts and status."""
    init_db()
    conn = get_connection()
    try:
        cursor = conn.execute(
            """
            SELECT 
                bidder_id,
                COUNT(*) as document_count,
                MAX(uploaded_at) as last_uploaded,
                CASE 
                    WHEN SUM(CASE WHEN status = 'verified' THEN 1 ELSE 0 END) > 0 THEN 'verified'
                    WHEN SUM(CASE WHEN status = 'flagged' THEN 1 ELSE 0 END) > 0 THEN 'flagged'
                    WHEN SUM(CASE WHEN status = 'submitted' THEN 1 ELSE 0 END) > 0 THEN 'submitted'
                    ELSE 'pending'
                END as overall_status
            FROM documents
            GROUP BY bidder_id
            HAVING overall_status IN ('submitted', 'verified', 'flagged')
            ORDER BY last_uploaded DESC
            """
        )
        return [dict(r) for r in cursor.fetchall()]
    finally:
        conn.close()


def get_all_bidders_summary() -> List[Dict[str, Any]]:
    """Retrieve summary for all bidders in the database regardless of status."""
    init_db()
    conn = get_connection()
    try:
        cursor = conn.execute(
            """
            SELECT 
                bidder_id,
                COUNT(*) as document_count,
                MAX(uploaded_at) as last_uploaded,
                CASE 
                    WHEN SUM(CASE WHEN status = 'verified' THEN 1 ELSE 0 END) > 0 THEN 'verified'
                    WHEN SUM(CASE WHEN status = 'flagged' THEN 1 ELSE 0 END) > 0 THEN 'flagged'
                    WHEN SUM(CASE WHEN status = 'submitted' THEN 1 ELSE 0 END) > 0 THEN 'submitted'
                    ELSE 'pending'
                END as overall_status
            FROM documents
            GROUP BY bidder_id
            ORDER BY last_uploaded DESC
            """
        )
        return [dict(r) for r in cursor.fetchall()]
    finally:
        conn.close()


def update_bidder_status(bidder_id: str, new_status: str, justification: str) -> bool:
    """Update a bidder's document status (e.g. 'verified' or 'flagged') and log audit trail."""
    init_db()
    clean_id = bidder_id.strip()
    now_iso = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    conn = get_connection()
    try:
        with conn:
            conn.execute(
                """
                UPDATE documents
                SET status = ?
                WHERE bidder_id = ?
                """,
                (new_status, clean_id),
            )
            conn.execute(
                """
                INSERT INTO audit_log (bidder_id, officer_action, justification, timestamp)
                VALUES (?, ?, ?, ?)
                """,
                (clean_id, new_status, justification.strip(), now_iso),
            )
        return True
    except Exception as exc:
        logger.error("Failed to update bidder status: %s", exc)
        return False
    finally:
        conn.close()


def get_audit_logs(bidder_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """Fetch audit log records, optionally filtered by bidder ID."""
    init_db()
    conn = get_connection()
    try:
        if bidder_id:
            cursor = conn.execute(
                """
                SELECT id, bidder_id, officer_action, justification, timestamp
                FROM audit_log
                WHERE bidder_id = ?
                ORDER BY id DESC
                """,
                (bidder_id.strip(),),
            )
        else:
            cursor = conn.execute(
                """
                SELECT id, bidder_id, officer_action, justification, timestamp
                FROM audit_log
                ORDER BY id DESC
                """
            )
        return [dict(r) for r in cursor.fetchall()]
    finally:
        conn.close()
