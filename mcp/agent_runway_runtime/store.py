from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import subprocess
import sys
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable


def utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def ensure_directory(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def tighten_windows_file_acl(path: Path) -> bool:
    current_user = os.environ.get("USERNAME") or os.environ.get("USER")
    if not current_user:
        return False
    commands = [
        ["icacls", str(path), "/inheritance:r"],
        ["icacls", str(path), "/grant:r", f"{current_user}:R"],
    ]
    for cmd in commands:
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            return False
    return True


@dataclass(frozen=True)
class ReceiptRecord:
    receipt_id: str
    session_id: str
    task_id: str | None
    source: str
    tool_name: str
    command_text: str | None
    exit_code: int | None
    metadata: dict[str, Any]
    created_at: str
    seq: int
    signature: str


@dataclass(frozen=True)
class MissionRecord:
    task_id: str
    session_id: str
    goal: str
    scope_boundary: str
    completion_criteria: list[str]
    red_lines: list[str]
    status: str
    slice_count: int
    retry_budget: int
    slice_budget: int
    created_at: str
    updated_at: str
    completed_at: str | None
    notes: dict[str, Any]


@dataclass(frozen=True)
class ApprovalRecord:
    token: str
    session_id: str
    task_id: str
    gate_type: str
    approved: bool
    reason: str
    after_receipt_seq: int
    created_at: str
    expires_at: str
    meta: dict[str, Any]


@dataclass(frozen=True)
class StuckAttemptRecord:
    attempt_id: int
    session_id: str
    task_id: str
    strategy_fingerprint: str
    summary: str
    receipt_ids: list[str]
    created_at: str


@dataclass(frozen=True)
class DecisionRecord:
    decision_id: int
    session_id: str
    task_id: str
    title: str
    choice_made: str
    alternatives_rejected: list[str]
    evidence_receipt_ids: list[str]
    reversibility: str
    reopen_triggers: list[str]
    created_at: str


@dataclass(frozen=True)
class CounterexampleCheckRecord:
    check_id: int
    session_id: str
    task_id: str
    hypothesis: str
    attempted_disconfirmers: list[str]
    outcome: str
    receipt_ids: list[str]
    surviving_risk: str
    created_at: str


class RuntimeStore:
    def __init__(self, db_path: str | None = None, secret: str | None = None) -> None:
        default_db = ".agent-runway/state.db"
        self.db_path = (
            Path(db_path or os.environ.get("ILH_DB_PATH", default_db))
            .expanduser()
            .resolve()
        )
        ensure_directory(self.db_path)
        self.secret = (
            secret
            or os.environ.get("ILH_HARNESS_SECRET")
            or self._load_or_create_secret()
        )
        self._init_db()

    def _load_or_create_secret(self) -> str:
        path = Path(
            os.environ.get("ILH_SECRET_PATH", "~/.config/agent-runway/secret.key")
        ).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            try:
                return path.read_text(encoding="utf-8").strip()
            except FileNotFoundError:
                pass
        value = secrets.token_hex(32)
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
        except FileExistsError:
            return path.read_text(encoding="utf-8").strip()
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(value + "\n")
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
        if sys.platform.startswith("win"):
            acl_tightened = tighten_windows_file_acl(path)
            mode = path.stat().st_mode & 0o777
            if not acl_tightened:
                sys.stderr.write(
                    f"[ILH WARNING] Windows secret ACL was not tightened by chmod; current mode is {oct(mode)} for {path}.\n"
                )
        return value

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        wal_row = conn.execute("PRAGMA journal_mode=WAL").fetchone()
        if wal_row and wal_row["journal_mode"] != "wal":
            sys.stderr.write(
                f"[ILH WARNING] SQLite journal_mode is {wal_row['journal_mode']!r} instead of 'wal'; "
                f"concurrent behavior may differ on this filesystem.\n"
            )
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    def _init_db(self) -> None:
        with closing(self._connect()) as conn, conn:
            self._migrate_mission_namespace_schema(conn)
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    host TEXT NOT NULL,
                    cwd TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS missions (
                    session_id TEXT NOT NULL,
                    task_id TEXT NOT NULL,
                    goal TEXT NOT NULL,
                    scope_boundary TEXT NOT NULL,
                    completion_criteria TEXT NOT NULL,
                    red_lines TEXT NOT NULL,
                    status TEXT NOT NULL,
                    slice_count INTEGER NOT NULL,
                    retry_budget INTEGER NOT NULL,
                    slice_budget INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    completed_at TEXT,
                    notes TEXT NOT NULL,
                    PRIMARY KEY(session_id, task_id),
                    FOREIGN KEY(session_id) REFERENCES sessions(session_id)
                );

                CREATE TABLE IF NOT EXISTS receipts (
                    receipt_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    task_id TEXT,
                    source TEXT NOT NULL,
                    tool_name TEXT NOT NULL,
                    command_text TEXT,
                    exit_code INTEGER,
                    metadata TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    seq INTEGER NOT NULL,
                    signature TEXT NOT NULL,
                    UNIQUE(session_id, seq),
                    FOREIGN KEY(session_id) REFERENCES sessions(session_id)
                );
                CREATE INDEX IF NOT EXISTS idx_receipts_session_seq ON receipts(session_id, seq);
                CREATE INDEX IF NOT EXISTS idx_receipts_task_seq ON receipts(task_id, seq);

                CREATE TABLE IF NOT EXISTS approvals (
                    token TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    task_id TEXT NOT NULL,
                    gate_type TEXT NOT NULL,
                    approved INTEGER NOT NULL,
                    reason TEXT NOT NULL,
                    after_receipt_seq INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    meta TEXT NOT NULL,
                    FOREIGN KEY(session_id) REFERENCES sessions(session_id),
                    FOREIGN KEY(session_id, task_id) REFERENCES missions(session_id, task_id)
                );
                CREATE INDEX IF NOT EXISTS idx_approvals_lookup ON approvals(session_id, task_id, gate_type, created_at);

                CREATE TABLE IF NOT EXISTS stuck_attempts (
                    attempt_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    task_id TEXT NOT NULL,
                    strategy_fingerprint TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    receipt_ids TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(session_id) REFERENCES sessions(session_id),
                    FOREIGN KEY(session_id, task_id) REFERENCES missions(session_id, task_id)
                );
                CREATE INDEX IF NOT EXISTS idx_stuck_attempts_lookup ON stuck_attempts(session_id, task_id, created_at);

                CREATE TABLE IF NOT EXISTS decision_records (
                    decision_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    task_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    choice_made TEXT NOT NULL,
                    alternatives_rejected TEXT NOT NULL,
                    evidence_receipt_ids TEXT NOT NULL,
                    reversibility TEXT NOT NULL,
                    reopen_triggers TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(session_id) REFERENCES sessions(session_id),
                    FOREIGN KEY(session_id, task_id) REFERENCES missions(session_id, task_id)
                );
                CREATE INDEX IF NOT EXISTS idx_decision_records_lookup ON decision_records(session_id, task_id, created_at);

                CREATE TABLE IF NOT EXISTS counterexample_checks (
                    check_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    task_id TEXT NOT NULL,
                    hypothesis TEXT NOT NULL,
                    attempted_disconfirmers TEXT NOT NULL,
                    outcome TEXT NOT NULL,
                    receipt_ids TEXT NOT NULL,
                    surviving_risk TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(session_id) REFERENCES sessions(session_id),
                    FOREIGN KEY(session_id, task_id) REFERENCES missions(session_id, task_id)
                );
                CREATE INDEX IF NOT EXISTS idx_counterexample_checks_lookup ON counterexample_checks(session_id, task_id, created_at);
                """
            )

    def _migrate_mission_namespace_schema(self, conn: sqlite3.Connection) -> None:
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='missions'"
        ).fetchone()
        if row is None:
            return

        pk_rows = conn.execute("PRAGMA table_info(missions)").fetchall()
        pk_columns = [entry["name"] for entry in pk_rows if entry["pk"]]
        if pk_columns != ["task_id"]:
            return

        conn.execute("PRAGMA foreign_keys=OFF")
        conn.executescript(
            """
            ALTER TABLE missions RENAME TO missions_old;
            ALTER TABLE approvals RENAME TO approvals_old;
            ALTER TABLE stuck_attempts RENAME TO stuck_attempts_old;
            ALTER TABLE decision_records RENAME TO decision_records_old;
            ALTER TABLE counterexample_checks RENAME TO counterexample_checks_old;

            CREATE TABLE missions (
                session_id TEXT NOT NULL,
                task_id TEXT NOT NULL,
                goal TEXT NOT NULL,
                scope_boundary TEXT NOT NULL,
                completion_criteria TEXT NOT NULL,
                red_lines TEXT NOT NULL,
                status TEXT NOT NULL,
                slice_count INTEGER NOT NULL,
                retry_budget INTEGER NOT NULL,
                slice_budget INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                completed_at TEXT,
                notes TEXT NOT NULL,
                PRIMARY KEY(session_id, task_id),
                FOREIGN KEY(session_id) REFERENCES sessions(session_id)
            );

            CREATE TABLE approvals (
                token TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                task_id TEXT NOT NULL,
                gate_type TEXT NOT NULL,
                approved INTEGER NOT NULL,
                reason TEXT NOT NULL,
                after_receipt_seq INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                meta TEXT NOT NULL,
                FOREIGN KEY(session_id) REFERENCES sessions(session_id),
                FOREIGN KEY(session_id, task_id) REFERENCES missions(session_id, task_id)
            );

            CREATE TABLE stuck_attempts (
                attempt_id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                task_id TEXT NOT NULL,
                strategy_fingerprint TEXT NOT NULL,
                summary TEXT NOT NULL,
                receipt_ids TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(session_id) REFERENCES sessions(session_id),
                FOREIGN KEY(session_id, task_id) REFERENCES missions(session_id, task_id)
            );

            CREATE TABLE decision_records (
                decision_id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                task_id TEXT NOT NULL,
                title TEXT NOT NULL,
                choice_made TEXT NOT NULL,
                alternatives_rejected TEXT NOT NULL,
                evidence_receipt_ids TEXT NOT NULL,
                reversibility TEXT NOT NULL,
                reopen_triggers TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(session_id) REFERENCES sessions(session_id),
                FOREIGN KEY(session_id, task_id) REFERENCES missions(session_id, task_id)
            );

            CREATE TABLE counterexample_checks (
                check_id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                task_id TEXT NOT NULL,
                hypothesis TEXT NOT NULL,
                attempted_disconfirmers TEXT NOT NULL,
                outcome TEXT NOT NULL,
                receipt_ids TEXT NOT NULL,
                surviving_risk TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(session_id) REFERENCES sessions(session_id),
                FOREIGN KEY(session_id, task_id) REFERENCES missions(session_id, task_id)
            );

            INSERT INTO missions(session_id, task_id, goal, scope_boundary, completion_criteria, red_lines, status,
                                 slice_count, retry_budget, slice_budget, created_at, updated_at, completed_at, notes)
            SELECT session_id, task_id, goal, scope_boundary, completion_criteria, red_lines, status,
                   slice_count, retry_budget, slice_budget, created_at, updated_at, completed_at, notes
            FROM missions_old;

            INSERT INTO approvals(token, session_id, task_id, gate_type, approved, reason,
                                  after_receipt_seq, created_at, expires_at, meta)
            SELECT token, session_id, task_id, gate_type, approved, reason,
                   after_receipt_seq, created_at, expires_at, meta
            FROM approvals_old;

            INSERT INTO stuck_attempts(attempt_id, session_id, task_id, strategy_fingerprint, summary, receipt_ids, created_at)
            SELECT attempt_id, session_id, task_id, strategy_fingerprint, summary, receipt_ids, created_at
            FROM stuck_attempts_old;

            INSERT INTO decision_records(decision_id, session_id, task_id, title, choice_made, alternatives_rejected,
                                         evidence_receipt_ids, reversibility, reopen_triggers, created_at)
            SELECT decision_id, session_id, task_id, title, choice_made, alternatives_rejected,
                   evidence_receipt_ids, reversibility, reopen_triggers, created_at
            FROM decision_records_old;

            INSERT INTO counterexample_checks(check_id, session_id, task_id, hypothesis, attempted_disconfirmers,
                                              outcome, receipt_ids, surviving_risk, created_at)
            SELECT check_id, session_id, task_id, hypothesis, attempted_disconfirmers,
                   outcome, receipt_ids, surviving_risk, created_at
            FROM counterexample_checks_old;

            DROP TABLE missions_old;
            DROP TABLE approvals_old;
            DROP TABLE stuck_attempts_old;
            DROP TABLE decision_records_old;
            DROP TABLE counterexample_checks_old;

            CREATE INDEX IF NOT EXISTS idx_approvals_lookup ON approvals(session_id, task_id, gate_type, created_at);
            CREATE INDEX IF NOT EXISTS idx_stuck_attempts_lookup ON stuck_attempts(session_id, task_id, created_at);
            CREATE INDEX IF NOT EXISTS idx_decision_records_lookup ON decision_records(session_id, task_id, created_at);
            CREATE INDEX IF NOT EXISTS idx_counterexample_checks_lookup ON counterexample_checks(session_id, task_id, created_at);
            """
        )
        conn.execute("PRAGMA foreign_keys=ON")

    def ensure_session(
        self, session_id: str, host: str = "unknown", cwd: str = "."
    ) -> None:
        # Never silently overwrite host/cwd on an existing session row. Earlier
        # callers (e.g. session_start hook) record the authoritative host/cwd;
        # later defensive calls must not clobber that with their defaults.
        # Only last_seen_at gets refreshed on conflict.
        now = utc_now()
        with closing(self._connect()) as conn, conn:
            conn.execute(
                """
                INSERT INTO sessions(session_id, host, cwd, created_at, last_seen_at)
                VALUES(?, ?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    host=CASE
                        WHEN sessions.host='unknown' AND excluded.host<>'unknown' THEN excluded.host
                        ELSE sessions.host
                    END,
                    cwd=CASE
                        WHEN sessions.cwd='.' AND excluded.cwd<>'.' THEN excluded.cwd
                        ELSE sessions.cwd
                    END,
                    last_seen_at=excluded.last_seen_at
                """,
                (session_id, host, cwd, now, now),
            )

    def create_mission(
        self,
        session_id: str,
        task_id: str,
        goal: str,
        completion_criteria: list[str],
        scope_boundary: str,
        red_lines: list[str],
        slice_budget: int,
        retry_budget: int,
        notes: dict[str, Any] | None = None,
    ) -> MissionRecord:
        now = utc_now()
        self.ensure_session(session_id)
        notes_with_epoch = dict(notes or {})
        with closing(self._connect()) as conn, conn:
            row = conn.execute(
                "SELECT COALESCE(MAX(seq), 0) AS seq FROM receipts WHERE session_id=? AND task_id=?",
                (session_id, task_id),
            ).fetchone()
            notes_with_epoch["mission_start_receipt_seq"] = int(row["seq"] if row else 0)
            conn.execute(
                "UPDATE missions SET status='superseded', updated_at=? WHERE session_id=? AND status='active' AND task_id<>?",
                (now, session_id, task_id),
            )
            conn.execute(
                "DELETE FROM stuck_attempts WHERE session_id=? AND task_id=?",
                (session_id, task_id),
            )
            conn.execute(
                "DELETE FROM approvals WHERE session_id=? AND task_id=?",
                (session_id, task_id),
            )
            conn.execute(
                "DELETE FROM decision_records WHERE session_id=? AND task_id=?",
                (session_id, task_id),
            )
            conn.execute(
                "DELETE FROM counterexample_checks WHERE session_id=? AND task_id=?",
                (session_id, task_id),
            )
            conn.execute(
                """
                INSERT INTO missions(session_id, task_id, goal, scope_boundary, completion_criteria, red_lines, status,
                                     slice_count, retry_budget, slice_budget, created_at, updated_at, completed_at, notes)
                VALUES(?, ?, ?, ?, ?, ?, 'active', 0, ?, ?, ?, ?, NULL, ?)
                ON CONFLICT(session_id, task_id) DO UPDATE SET
                    goal=excluded.goal,
                    scope_boundary=excluded.scope_boundary,
                    completion_criteria=excluded.completion_criteria,
                    red_lines=excluded.red_lines,
                    status='active',
                    slice_count=0,
                    retry_budget=excluded.retry_budget,
                    slice_budget=excluded.slice_budget,
                    created_at=excluded.created_at,
                    updated_at=excluded.updated_at,
                    notes=excluded.notes,
                    completed_at=NULL
                """,
                (
                    session_id,
                    task_id,
                    goal,
                    scope_boundary,
                    canonical_json(completion_criteria),
                    canonical_json(red_lines),
                    retry_budget,
                    slice_budget,
                    now,
                    now,
                    canonical_json(notes_with_epoch),
                ),
            )
        return self.get_mission(session_id, task_id)

    def get_mission(self, session_id: str, task_id: str) -> MissionRecord:
        with closing(self._connect()) as conn, conn:
            row = conn.execute(
                "SELECT * FROM missions WHERE session_id=? AND task_id=?",
                (session_id, task_id),
            ).fetchone()
        if not row:
            raise KeyError(
                f"Unknown mission: session_id={session_id!r}, task_id={task_id!r}"
            )
        return self._row_to_mission(row)

    def get_active_mission(
        self, session_id: str, task_id: str | None = None
    ) -> MissionRecord | None:
        query = "SELECT * FROM missions WHERE session_id=? AND status='active'"
        params: list[Any] = [session_id]
        if task_id:
            query += " AND task_id=?"
            params.append(task_id)
        query += " ORDER BY updated_at DESC LIMIT 1"
        with closing(self._connect()) as conn, conn:
            row = conn.execute(query, params).fetchone()
        return self._row_to_mission(row) if row else None

    def get_latest_mission(self, session_id: str) -> MissionRecord | None:
        with closing(self._connect()) as conn, conn:
            row = conn.execute(
                "SELECT * FROM missions WHERE session_id=? ORDER BY updated_at DESC LIMIT 1",
                (session_id,),
            ).fetchone()
        return self._row_to_mission(row) if row else None

    def _row_to_mission(self, row: sqlite3.Row) -> MissionRecord:
        return MissionRecord(
            task_id=row["task_id"],
            session_id=row["session_id"],
            goal=row["goal"],
            scope_boundary=row["scope_boundary"],
            completion_criteria=json.loads(row["completion_criteria"]),
            red_lines=json.loads(row["red_lines"]),
            status=row["status"],
            slice_count=int(row["slice_count"]),
            retry_budget=int(row["retry_budget"]),
            slice_budget=int(row["slice_budget"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            completed_at=row["completed_at"],
            notes=json.loads(row["notes"]),
        )

    def mark_completed(
        self, session_id: str, task_id: str, notes: dict[str, Any] | None = None
    ) -> MissionRecord:
        now = utc_now()
        with closing(self._connect()) as conn, conn:
            conn.execute(
                "UPDATE missions SET status='completed', completed_at=?, updated_at=?, notes=? WHERE session_id=? AND task_id=?",
                (now, now, canonical_json(notes or {}), session_id, task_id),
            )
        return self.get_mission(session_id, task_id)

    def increment_slice(self, session_id: str, task_id: str) -> MissionRecord:
        now = utc_now()
        with closing(self._connect()) as conn, conn:
            conn.execute(
                "UPDATE missions SET slice_count=slice_count+1, updated_at=? WHERE session_id=? AND task_id=?",
                (now, session_id, task_id),
            )
        return self.get_mission(session_id, task_id)

    def record_stuck_attempt(
        self,
        session_id: str,
        task_id: str,
        strategy_fingerprint: str,
        summary: str,
        receipt_ids: list[str],
    ) -> StuckAttemptRecord:
        now = utc_now()
        with closing(self._connect()) as conn, conn:
            cur = conn.execute(
                """
                INSERT INTO stuck_attempts(session_id, task_id, strategy_fingerprint, summary, receipt_ids, created_at)
                VALUES(?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    task_id,
                    strategy_fingerprint,
                    summary,
                    canonical_json(receipt_ids),
                    now,
                ),
            )
            attempt_id = int(cur.lastrowid)
        return StuckAttemptRecord(
            attempt_id,
            session_id,
            task_id,
            strategy_fingerprint,
            summary,
            receipt_ids,
            now,
        )

    def list_stuck_attempts(
        self, session_id: str, task_id: str
    ) -> list[StuckAttemptRecord]:
        with closing(self._connect()) as conn, conn:
            rows = conn.execute(
                "SELECT * FROM stuck_attempts WHERE session_id=? AND task_id=? ORDER BY created_at ASC",
                (session_id, task_id),
            ).fetchall()
        return [
            StuckAttemptRecord(
                attempt_id=int(row["attempt_id"]),
                session_id=row["session_id"],
                task_id=row["task_id"],
                strategy_fingerprint=row["strategy_fingerprint"],
                summary=row["summary"],
                receipt_ids=json.loads(row["receipt_ids"]),
                created_at=row["created_at"],
            )
            for row in rows
        ]

    def record_decision_record(
        self,
        session_id: str,
        task_id: str,
        title: str,
        choice_made: str,
        alternatives_rejected: list[str],
        evidence_receipt_ids: list[str],
        reversibility: str,
        reopen_triggers: list[str],
    ) -> DecisionRecord:
        now = utc_now()
        with closing(self._connect()) as conn, conn:
            cur = conn.execute(
                """
                INSERT INTO decision_records(session_id, task_id, title, choice_made, alternatives_rejected,
                                             evidence_receipt_ids, reversibility, reopen_triggers, created_at)
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    task_id,
                    title,
                    choice_made,
                    canonical_json(alternatives_rejected),
                    canonical_json(evidence_receipt_ids),
                    reversibility,
                    canonical_json(reopen_triggers),
                    now,
                ),
            )
            decision_id = int(cur.lastrowid)
        return DecisionRecord(
            decision_id,
            session_id,
            task_id,
            title,
            choice_made,
            alternatives_rejected,
            evidence_receipt_ids,
            reversibility,
            reopen_triggers,
            now,
        )

    def list_decision_records(
        self, session_id: str, task_id: str
    ) -> list[DecisionRecord]:
        with closing(self._connect()) as conn, conn:
            rows = conn.execute(
                "SELECT * FROM decision_records WHERE session_id=? AND task_id=? ORDER BY created_at ASC",
                (session_id, task_id),
            ).fetchall()
        return [
            DecisionRecord(
                decision_id=int(row["decision_id"]),
                session_id=row["session_id"],
                task_id=row["task_id"],
                title=row["title"],
                choice_made=row["choice_made"],
                alternatives_rejected=json.loads(row["alternatives_rejected"]),
                evidence_receipt_ids=json.loads(row["evidence_receipt_ids"]),
                reversibility=row["reversibility"],
                reopen_triggers=json.loads(row["reopen_triggers"]),
                created_at=row["created_at"],
            )
            for row in rows
        ]

    def record_counterexample_check(
        self,
        session_id: str,
        task_id: str,
        hypothesis: str,
        attempted_disconfirmers: list[str],
        outcome: str,
        receipt_ids: list[str],
        surviving_risk: str,
    ) -> CounterexampleCheckRecord:
        now = utc_now()
        with closing(self._connect()) as conn, conn:
            cur = conn.execute(
                """
                INSERT INTO counterexample_checks(session_id, task_id, hypothesis, attempted_disconfirmers,
                                                  outcome, receipt_ids, surviving_risk, created_at)
                VALUES(?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    task_id,
                    hypothesis,
                    canonical_json(attempted_disconfirmers),
                    outcome,
                    canonical_json(receipt_ids),
                    surviving_risk,
                    now,
                ),
            )
            check_id = int(cur.lastrowid)
        return CounterexampleCheckRecord(
            check_id,
            session_id,
            task_id,
            hypothesis,
            attempted_disconfirmers,
            outcome,
            receipt_ids,
            surviving_risk,
            now,
        )

    def list_counterexample_checks(
        self, session_id: str, task_id: str
    ) -> list[CounterexampleCheckRecord]:
        with closing(self._connect()) as conn, conn:
            rows = conn.execute(
                "SELECT * FROM counterexample_checks WHERE session_id=? AND task_id=? ORDER BY created_at ASC",
                (session_id, task_id),
            ).fetchall()
        return [
            CounterexampleCheckRecord(
                check_id=int(row["check_id"]),
                session_id=row["session_id"],
                task_id=row["task_id"],
                hypothesis=row["hypothesis"],
                attempted_disconfirmers=json.loads(row["attempted_disconfirmers"]),
                outcome=row["outcome"],
                receipt_ids=json.loads(row["receipt_ids"]),
                surviving_risk=row["surviving_risk"],
                created_at=row["created_at"],
            )
            for row in rows
        ]

    def sign_receipt_payload(self, payload: dict[str, Any]) -> tuple[str, str]:
        message = canonical_json(payload).encode("utf-8")
        digest = hmac.new(
            self.secret.encode("utf-8"), message, hashlib.sha256
        ).hexdigest()
        receipt_id = hashlib.sha256(
            (digest + canonical_json(payload)).encode("utf-8")
        ).hexdigest()[:20]
        return receipt_id, digest

    def verify_receipt(self, receipt: ReceiptRecord) -> bool:
        payload = {
            "session_id": receipt.session_id,
            "task_id": receipt.task_id,
            "source": receipt.source,
            "tool_name": receipt.tool_name,
            "command_text": receipt.command_text,
            "exit_code": receipt.exit_code,
            "metadata": receipt.metadata,
            "created_at": receipt.created_at,
        }
        expected_id, expected_signature = self.sign_receipt_payload(payload)
        return (
            hmac.compare_digest(expected_id, receipt.receipt_id)
            and hmac.compare_digest(expected_signature, receipt.signature)
        )

    def record_receipt(
        self,
        session_id: str,
        source: str,
        tool_name: str,
        command_text: str | None,
        exit_code: int | None,
        metadata: dict[str, Any] | None = None,
        task_id: str | None = None,
        created_at: str | None = None,
        signature: str | None = None,
        receipt_id: str | None = None,
    ) -> ReceiptRecord:
        metadata = dict(metadata or {})
        if receipt_id is None and signature is None and "_receipt_nonce" not in metadata:
            metadata["_receipt_nonce"] = secrets.token_hex(8)
        created_at = created_at or utc_now()
        payload = {
            "session_id": session_id,
            "task_id": task_id,
            "source": source,
            "tool_name": tool_name,
            "command_text": command_text,
            "exit_code": exit_code,
            "metadata": metadata,
            "created_at": created_at,
        }
        computed_receipt_id, computed_signature = self.sign_receipt_payload(payload)
        receipt_id = receipt_id or computed_receipt_id
        signature = signature or computed_signature
        if signature != computed_signature or receipt_id != computed_receipt_id:
            raise ValueError("Receipt signature mismatch")
        self.ensure_session(session_id)
        with closing(self._connect()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT COALESCE(MAX(seq), 0) + 1 AS next_seq FROM receipts WHERE session_id=?",
                (session_id,),
            ).fetchone()
            seq = int(row["next_seq"])
            existing = conn.execute(
                "SELECT seq FROM receipts WHERE receipt_id=?",
                (receipt_id,),
            ).fetchone()
            if existing is None:
                conn.execute(
                    """
                    INSERT INTO receipts(receipt_id, session_id, task_id, source, tool_name, command_text,
                                        exit_code, metadata, created_at, seq, signature)
                    VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        receipt_id,
                        session_id,
                        task_id,
                        source,
                        tool_name,
                        command_text,
                        exit_code,
                        canonical_json(metadata),
                        created_at,
                        seq,
                        signature,
                    ),
                )
            else:
                seq = int(existing["seq"])
            conn.commit()
        return ReceiptRecord(
            receipt_id,
            session_id,
            task_id,
            source,
            tool_name,
            command_text,
            exit_code,
            metadata,
            created_at,
            seq,
            signature,
        )

    def get_receipts(
        self,
        receipt_ids: Iterable[str],
        session_id: str | None = None,
        task_id: str | None = None,
    ) -> list[ReceiptRecord]:
        ids = list(dict.fromkeys([rid for rid in receipt_ids if rid]))
        if not ids:
            return []
        placeholders = ",".join("?" for _ in ids)
        query = f"SELECT * FROM receipts WHERE receipt_id IN ({placeholders})"
        params: list[Any] = ids[:]
        if session_id:
            query += " AND session_id=?"
            params.append(session_id)
        if task_id is not None:
            query += " AND task_id IS ?"
            params.append(task_id)
        with closing(self._connect()) as conn, conn:
            rows = conn.execute(query, params).fetchall()
        return [
            ReceiptRecord(
                receipt_id=row["receipt_id"],
                session_id=row["session_id"],
                task_id=row["task_id"],
                source=row["source"],
                tool_name=row["tool_name"],
                command_text=row["command_text"],
                exit_code=row["exit_code"],
                metadata=json.loads(row["metadata"]),
                created_at=row["created_at"],
                seq=int(row["seq"]),
                signature=row["signature"],
            )
            for row in rows
        ]

    def list_recent_receipts(
        self, session_id: str, task_id: str | None = None, limit: int = 10
    ) -> list[ReceiptRecord]:
        query = "SELECT * FROM receipts WHERE session_id=?"
        params: list[Any] = [session_id]
        if task_id:
            query += " AND task_id=?"
            params.append(task_id)
        query += " ORDER BY seq DESC LIMIT ?"
        params.append(limit)
        with closing(self._connect()) as conn, conn:
            rows = conn.execute(query, params).fetchall()
        return [
            ReceiptRecord(
                receipt_id=row["receipt_id"],
                session_id=row["session_id"],
                task_id=row["task_id"],
                source=row["source"],
                tool_name=row["tool_name"],
                command_text=row["command_text"],
                exit_code=row["exit_code"],
                metadata=json.loads(row["metadata"]),
                created_at=row["created_at"],
                seq=int(row["seq"]),
                signature=row["signature"],
            )
            for row in rows
        ]

    def latest_receipt_seq(self, session_id: str, task_id: str | None = None) -> int:
        query = "SELECT COALESCE(MAX(seq), 0) AS seq FROM receipts WHERE session_id=?"
        params: list[Any] = [session_id]
        if task_id:
            query += " AND task_id=?"
            params.append(task_id)
        with closing(self._connect()) as conn, conn:
            row = conn.execute(query, params).fetchone()
        return int(row["seq"])

    def latest_tool_seq(
        self, session_id: str, task_id: str, tool_names: Iterable[str]
    ) -> int:
        names = [name for name in tool_names if name]
        if not names:
            return 0
        placeholders = ",".join("?" for _ in names)
        query = (
            "SELECT COALESCE(MAX(seq), 0) AS seq FROM receipts "
            f"WHERE session_id=? AND task_id=? AND tool_name IN ({placeholders})"
        )
        with closing(self._connect()) as conn, conn:
            row = conn.execute(query, [session_id, task_id, *names]).fetchone()
        return int(row["seq"])

    def create_approval(
        self,
        session_id: str,
        task_id: str,
        gate_type: str,
        approved: bool,
        reason: str,
        after_receipt_seq: int,
        ttl_seconds: int = 600,
        meta: dict[str, Any] | None = None,
    ) -> ApprovalRecord:
        created_at = utc_now()
        expires_at = (
            (datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds))
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z")
        )
        token = secrets.token_urlsafe(18)
        with closing(self._connect()) as conn, conn:
            conn.execute(
                """
                INSERT INTO approvals(token, session_id, task_id, gate_type, approved, reason,
                                      after_receipt_seq, created_at, expires_at, meta)
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    token,
                    session_id,
                    task_id,
                    gate_type,
                    1 if approved else 0,
                    reason,
                    after_receipt_seq,
                    created_at,
                    expires_at,
                    canonical_json(meta or {}),
                ),
            )
        return ApprovalRecord(
            token,
            session_id,
            task_id,
            gate_type,
            approved,
            reason,
            after_receipt_seq,
            created_at,
            expires_at,
            meta or {},
        )

    def latest_approval(
        self, session_id: str, task_id: str, gate_type: str | None = None
    ) -> ApprovalRecord | None:
        query = "SELECT * FROM approvals WHERE session_id=? AND task_id=?"
        params: list[Any] = [session_id, task_id]
        if gate_type:
            query += " AND gate_type=?"
            params.append(gate_type)
        query += " ORDER BY created_at DESC, rowid DESC LIMIT 1"
        with closing(self._connect()) as conn, conn:
            row = conn.execute(query, params).fetchone()
        if not row:
            return None
        return ApprovalRecord(
            token=row["token"],
            session_id=row["session_id"],
            task_id=row["task_id"],
            gate_type=row["gate_type"],
            approved=bool(row["approved"]),
            reason=row["reason"],
            after_receipt_seq=int(row["after_receipt_seq"]),
            created_at=row["created_at"],
            expires_at=row["expires_at"],
            meta=json.loads(row["meta"]),
        )

    def is_approval_fresh(
        self, approval: ApprovalRecord | None, session_id: str, task_id: str
    ) -> bool:
        """
        Check if an approval is still fresh (valid for use).
        
        Design note: This uses session-level receipt freshness (latest_receipt_seq(session_id))
        rather than task-level (latest_receipt_seq(session_id, task_id)). This is a deliberate
        design tradeoff to support future multi-task concurrency within a session:
        
        - In the current single-active-task model, this is slightly more permissive than necessary
        - In a future multi-task model, this prevents cross-task receipt pollution
        - The tradeoff: session-level freshness means any receipt in the session invalidates
          all approvals, even if they belong to different tasks
        
        This is not a bug, but a forward-looking design choice that prioritizes safety
        (conservative invalidation) over precision in the current single-task scenario.
        """
        if approval is None or not approval.approved:
            return False
        latest = self.latest_approval(session_id, task_id, approval.gate_type)
        if latest is None or latest.token != approval.token:
            return False
        expires = datetime.fromisoformat(approval.expires_at.replace("Z", "+00:00"))
        if expires < datetime.now(timezone.utc):
            return False
        return approval.after_receipt_seq >= self.latest_receipt_seq(session_id)
