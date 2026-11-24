"""Crash-safe, account-scoped claims and receipts for non-idempotent draft creation."""
import hashlib
import json
import os
import tempfile
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4


class DeliveryJournal:
    def __init__(self, path="data/delivery.sqlite3"):
        self.path = Path(path)

    @contextmanager
    def _transaction(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        try:
            with db:
                db.execute("""CREATE TABLE IF NOT EXISTS delivery (
                    attempt_id TEXT PRIMARY KEY, account TEXT NOT NULL,
                    operation_id TEXT NOT NULL, status TEXT NOT NULL, title TEXT NOT NULL,
                    media_id TEXT, errmsg TEXT, context TEXT NOT NULL)""")
                db.execute("""CREATE UNIQUE INDEX IF NOT EXISTS active_delivery
                    ON delivery(account, operation_id) WHERE status != 'FAILED'""")
                db.execute("BEGIN IMMEDIATE")
                yield db
        finally:
            db.close()

    def claim(self, account, operation_id, title, context):
        with self._transaction() as db:
            row = db.execute("""SELECT * FROM delivery WHERE account=? AND operation_id=?
                                AND status!='FAILED'""", (account, operation_id)).fetchone()
            if row:
                return self._decode(row), False
            attempt = uuid4().hex
            db.execute("""INSERT INTO delivery VALUES(?,?,?,'CLOUD_UNCERTAIN',?,NULL,NULL,?)""",
                       (attempt, account, operation_id, title, json.dumps(context, ensure_ascii=False)))
            return self._get(db, account, attempt), True

    @staticmethod
    def _decode(row):
        result = dict(row)
        result["context"] = json.loads(result["context"])
        if result["media_id"] is None:
            del result["media_id"]
        return result

    def _get(self, db, account, attempt):
        row = db.execute("SELECT * FROM delivery WHERE account=? AND attempt_id=?",
                         (account, attempt)).fetchone()
        if row is None:
            raise KeyError(attempt)
        return self._decode(row)

    def get(self, account, attempt):
        with self._transaction() as db:
            return self._get(db, account, attempt)

    def resolve(self, account, attempt, *, media_id=None, rejection=None):
        if bool(media_id) == bool(rejection):
            raise ValueError("Expected one receipt or rejection")
        with self._transaction() as db:
            db.execute("""UPDATE delivery SET status=?, media_id=?, errmsg=?
                          WHERE account=? AND attempt_id=? AND status='CLOUD_UNCERTAIN'""",
                       ("FAILED" if rejection else "DRAFT_PENDING_RECORD", media_id,
                        rejection, account, attempt))
            return self._get(db, account, attempt)

    def _receipt_path(self, account, attempt):
        key = hashlib.sha256(f"{account}:{attempt}".encode()).hexdigest()
        return self.path.parent / "delivery_receipts" / (key + ".json")

    def save_fallback_receipt(self, account, attempt, media_id):
        path = self._receipt_path(account, attempt)
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=path.parent, mode="w", encoding="utf8",
                                         delete=False) as out:
            temporary = Path(out.name)
        try:
            with temporary.open("w", encoding="utf8") as stream:
                json.dump(media_id, stream)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)

    def fallback_receipt(self, account, attempt):
        try:
            return json.loads(self._receipt_path(account, attempt).read_text("utf8"))
        except FileNotFoundError:
            return None

    def recorded(self, account, attempt):
        with self._transaction() as db:
            db.execute("""UPDATE delivery SET status='DRAFT' WHERE account=? AND attempt_id=?
                          AND status='DRAFT_PENDING_RECORD'""", (account, attempt))
            row = self._get(db, account, attempt)
            if row["status"] != "DRAFT":
                raise ValueError("Missing confirmed draft receipt")
            return row

    def latest_operation(self, account, operation_id):
        with self._transaction() as db:
            row = db.execute("""SELECT * FROM delivery WHERE account=? AND operation_id=?
                                ORDER BY rowid DESC LIMIT 1""", (account, operation_id)).fetchone()
            return self._decode(row) if row else None

    def retire_confirmed_draft(self, account, attempt, media_id):
        """Release the business key only for the exact draft proven absent in reconciliation."""
        with self._transaction() as db:
            db.execute("""UPDATE delivery SET status='ARCHIVED', operation_id='archived:' || attempt_id
                          WHERE account=? AND attempt_id=? AND media_id=? AND status='DRAFT'""",
                       (account, attempt, media_id))

    def pending(self, account):
        with self._transaction() as db:
            return [self._decode(row) for row in db.execute(
                """SELECT * FROM delivery WHERE account=? AND status IN
                   ('CLOUD_UNCERTAIN','DRAFT_PENDING_RECORD') ORDER BY rowid""", (account,))]
