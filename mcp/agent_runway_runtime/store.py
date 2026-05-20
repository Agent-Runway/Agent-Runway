from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import subprocess
import sys
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

SUBAGENT_TERMINAL_STATUSES = frozenset({"completed", "failed", "abandoned", "rejected"})
SECRET_KEY_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class _UnsetTaskId:
    pass


_TASK_ID_UNSET = _UnsetTaskId()


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


def normalize_cwd(cwd: str) -> str:
    return str(Path(cwd or ".").expanduser().resolve())


def tighten_windows_file_acl(path: Path) -> bool:
    current_user = os.environ.get("USERNAME") or os.environ.get("USER")
    if not current_user:
        return False
    commands = [
        ["icacls", str(path), "/inheritance:r"],
        ["icacls", str(path), "/grant:r", f"{current_user}:R"],
    ]
    for cmd in commands:
        try:
            result = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )
        except OSError:
            return False
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


@dataclass(frozen=True)
class SubagentSpanRecord:
    child_span_id: str
    session_id: str
    task_id: str
    host: str
    subagent_type: str
    host_child_id: str
    context_mode: str
    workspace_kind: str
    status: str
    delegated_scope: str
    delegated_budget: dict[str, Any]
    budget_consumed: dict[str, Any]
    started_at: str
    ended_at: str | None
    transcript_ref: str
    artifact_refs: list[str]
    last_message: str
    parent_receipt_seq: int
    terminal_receipt_seq: int


@dataclass(frozen=True)
class SubagentHandoffRecord:
    handoff_id: int
    child_span_id: str
    session_id: str
    task_id: str
    summary: str
    verified_claims: list[dict[str, Any]]
    receipt_ids: list[str]
    risks: list[str]
    unverified_items: list[str]
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
                return self._read_secret_file(path)
            except FileNotFoundError:
                pass
        value = secrets.token_hex(32)
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
        except FileExistsError:
            return self._read_secret_file(path)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(value + "\n")
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
        if sys.platform.startswith("win"):
            acl_tightened = tighten_windows_file_acl(path)
            if not acl_tightened:
                path.unlink(missing_ok=True)
                raise PermissionError(
                    f"Windows secret ACL could not be tightened for {path}; refusing to continue."
                )
        return value

    def _read_secret_file(self, path: Path) -> str:
        value = path.read_text(encoding="utf-8").strip()
        if not SECRET_KEY_PATTERN.fullmatch(value):
            raise ValueError(f"{path} secret.key must contain 64 lowercase hex characters.")
        return value

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        try:
            conn.row_factory = sqlite3.Row
            wal_row = conn.execute("PRAGMA journal_mode=WAL").fetchone()
            if wal_row and wal_row["journal_mode"] != "wal":
                sys.stderr.write(
                    f"[ILH WARNING] SQLite journal_mode is {wal_row['journal_mode']!r} instead of 'wal'; "
                    f"concurrent behavior may differ on this filesystem.\n"
                )
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA busy_timeout=5000")
        except Exception:
            conn.close()
            raise
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

                CREATE TABLE IF NOT EXISTS host_session_bindings (
                    host_session_id TEXT PRIMARY KEY,
                    mission_session_id TEXT NOT NULL,
                    task_id TEXT NOT NULL,
                    source TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(host_session_id) REFERENCES sessions(session_id),
                    FOREIGN KEY(mission_session_id, task_id) REFERENCES missions(session_id, task_id)
                );
                CREATE INDEX IF NOT EXISTS idx_host_session_bindings_mission
                    ON host_session_bindings(mission_session_id, task_id);

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

                CREATE TABLE IF NOT EXISTS subagent_spans (
                    child_span_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    task_id TEXT NOT NULL,
                    host TEXT NOT NULL,
                    subagent_type TEXT NOT NULL,
                    host_child_id TEXT NOT NULL,
                    context_mode TEXT NOT NULL,
                    workspace_kind TEXT NOT NULL,
                    status TEXT NOT NULL,
                    delegated_scope TEXT NOT NULL,
                    delegated_budget TEXT NOT NULL,
                    budget_consumed TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    ended_at TEXT,
                    transcript_ref TEXT NOT NULL,
                    artifact_refs TEXT NOT NULL,
                    last_message TEXT NOT NULL,
                    parent_receipt_seq INTEGER NOT NULL,
                    terminal_receipt_seq INTEGER NOT NULL DEFAULT 0,
                    FOREIGN KEY(session_id) REFERENCES sessions(session_id),
                    FOREIGN KEY(session_id, task_id) REFERENCES missions(session_id, task_id)
                );
                CREATE INDEX IF NOT EXISTS idx_subagent_spans_lookup ON subagent_spans(session_id, task_id, started_at);
                CREATE UNIQUE INDEX IF NOT EXISTS idx_subagent_spans_host_child_unique
                    ON subagent_spans(session_id, task_id, host, host_child_id)
                    WHERE host_child_id<>'';

                CREATE TABLE IF NOT EXISTS subagent_handoffs (
                    handoff_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    child_span_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    task_id TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    verified_claims TEXT NOT NULL,
                    receipt_ids TEXT NOT NULL,
                    risks TEXT NOT NULL,
                    unverified_items TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(child_span_id) REFERENCES subagent_spans(child_span_id),
                    FOREIGN KEY(session_id) REFERENCES sessions(session_id),
                    FOREIGN KEY(session_id, task_id) REFERENCES missions(session_id, task_id)
                );
                CREATE INDEX IF NOT EXISTS idx_subagent_handoffs_lookup ON subagent_handoffs(session_id, task_id, child_span_id, created_at);
                """
            )

    def _migrate_mission_namespace_schema(self, conn: sqlite3.Connection) -> None:
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='missions'"
        ).fetchone()
        if row is None:
            return

        self._migrate_subagent_terminal_receipt_seq(conn)

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

    def _migrate_subagent_terminal_receipt_seq(self, conn: sqlite3.Connection) -> None:
        if not self._table_exists(conn, "subagent_spans"):
            return
        columns = {entry["name"] for entry in conn.execute("PRAGMA table_info(subagent_spans)")}
        if "terminal_receipt_seq" in columns:
            return

        conn.execute(
            "ALTER TABLE subagent_spans ADD COLUMN terminal_receipt_seq INTEGER NOT NULL DEFAULT 0"
        )
        if not self._table_exists(conn, "receipts"):
            return
        conn.execute(
            """
            UPDATE subagent_spans
            SET terminal_receipt_seq=COALESCE((
                SELECT MAX(receipts.seq)
                FROM receipts
                WHERE receipts.session_id=subagent_spans.session_id
                  AND receipts.created_at<=subagent_spans.ended_at
            ), 0)
            WHERE ended_at IS NOT NULL
            """
        )

    def _table_exists(self, conn: sqlite3.Connection, table_name: str) -> bool:
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (table_name,),
        ).fetchone()
        return row is not None

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

    def bind_host_session_to_mission(
        self, host_session_id: str, mission: MissionRecord, source: str = ""
    ) -> None:
        now = utc_now()
        self.ensure_session(host_session_id)
        with closing(self._connect()) as conn, conn:
            conn.execute(
                """
                INSERT INTO host_session_bindings(host_session_id, mission_session_id, task_id, source, created_at, updated_at)
                VALUES(?, ?, ?, ?, ?, ?)
                ON CONFLICT(host_session_id) DO UPDATE SET
                    mission_session_id=excluded.mission_session_id,
                    task_id=excluded.task_id,
                    source=excluded.source,
                    updated_at=excluded.updated_at
                """,
                (host_session_id, mission.session_id, mission.task_id, source, now, now),
            )

    def bound_active_mission_for_host_session(
        self, host_session_id: str
    ) -> MissionRecord | None:
        with closing(self._connect()) as conn, conn:
            row = conn.execute(
                """
                SELECT missions.*
                FROM host_session_bindings
                JOIN missions
                  ON missions.session_id=host_session_bindings.mission_session_id
                 AND missions.task_id=host_session_bindings.task_id
                WHERE host_session_bindings.host_session_id=?
                  AND missions.status='active'
                ORDER BY host_session_bindings.updated_at DESC
                LIMIT 1
                """,
                (host_session_id,),
            ).fetchone()
        return self._row_to_mission(row) if row else None

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
        with closing(self._connect()) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            active = conn.execute(
                "SELECT 1 FROM missions WHERE session_id=? AND task_id=? AND status='active' LIMIT 1",
                (session_id, task_id),
            ).fetchone()
            if active is not None:
                raise ValueError("mission_lock does not allow relocking an active mission")
            existing = conn.execute(
                "SELECT status FROM missions WHERE session_id=? AND task_id=? LIMIT 1",
                (session_id, task_id),
            ).fetchone()
            if existing is not None:
                raise ValueError(
                    "mission_lock does not allow reusing an existing mission task_id"
                )
            row = conn.execute(
                "SELECT COALESCE(MAX(seq), 0) AS seq FROM receipts WHERE session_id=?",
                (session_id,),
            ).fetchone()
            notes_with_epoch = dict(notes or {})
            notes_with_epoch["mission_start_receipt_seq"] = int(row["seq"] if row else 0)
            conn.execute(
                """
                INSERT INTO missions(session_id, task_id, goal, scope_boundary, completion_criteria, red_lines, status,
                                     slice_count, retry_budget, slice_budget, created_at, updated_at, completed_at, notes)
                VALUES(?, ?, ?, ?, ?, ?, 'active', 0, ?, ?, ?, ?, NULL, ?)
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

    def _delete_transient_approvals(
        self, conn: sqlite3.Connection, session_id: str, task_id: str
    ) -> None:
        rows = conn.execute(
            "SELECT token, meta FROM approvals WHERE session_id=? AND task_id=?",
            (session_id, task_id),
        ).fetchall()
        tokens = [row["token"] for row in rows if not self._is_standing_boundary(row["meta"])]
        conn.executemany("DELETE FROM approvals WHERE token=?", [(token,) for token in tokens])

    def _is_standing_boundary(self, meta_text: str) -> bool:
        try:
            meta = json.loads(meta_text)
        except json.JSONDecodeError:
            return False
        return meta.get("authorization_kind") == "standing_boundary"

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
        params = self._session_mission_params(session_id, task_id)
        if task_id:
            query += " AND task_id=?"
        query += " ORDER BY updated_at DESC LIMIT 1"
        with closing(self._connect()) as conn, conn:
            row = conn.execute(query, params).fetchone()
        return self._row_to_mission(row) if row else None

    def list_active_missions(
        self, session_id: str, task_id: str | None = None
    ) -> list[MissionRecord]:
        query = "SELECT * FROM missions WHERE session_id=? AND status='active'"
        params = self._session_mission_params(session_id, task_id)
        if task_id:
            query += " AND task_id=?"
        query += " ORDER BY updated_at DESC"
        with closing(self._connect()) as conn, conn:
            rows = conn.execute(query, params).fetchall()
        return [self._row_to_mission(row) for row in rows]

    def _session_mission_params(self, session_id: str, task_id: str | None) -> list[Any]:
        params: list[Any] = [session_id]
        if task_id:
            params.append(task_id)
        return params

    def get_latest_mission(self, session_id: str) -> MissionRecord | None:
        with closing(self._connect()) as conn, conn:
            row = conn.execute(
                "SELECT * FROM missions WHERE session_id=? ORDER BY updated_at DESC LIMIT 1",
                (session_id,),
            ).fetchone()
        return self._row_to_mission(row) if row else None

    def get_latest_active_mission_by_cwd(self, cwd: str) -> MissionRecord | None:
        matches = self.list_active_missions_by_cwd(cwd)
        return self._single_mission_or_none(matches)

    def list_active_missions_by_cwd(self, cwd: str) -> list[MissionRecord]:
        normalized_cwd = normalize_cwd(cwd)
        with closing(self._connect()) as conn, conn:
            rows = conn.execute(
                """
                SELECT missions.*, sessions.cwd AS session_cwd
                FROM missions
                JOIN sessions ON sessions.session_id = missions.session_id
                WHERE missions.status='active'
                ORDER BY missions.updated_at DESC
                """,
            ).fetchall()
        matches = [row for row in rows if normalize_cwd(row["session_cwd"]) == normalized_cwd]
        return [self._row_to_mission(row) for row in matches]

    def _single_mission_or_none(self, missions: list[MissionRecord]) -> MissionRecord | None:
        if len(missions) != 1:
            return None
        return missions[0]

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
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT status, notes FROM missions WHERE session_id=? AND task_id=?",
                (session_id, task_id),
            ).fetchone()
            if row is None:
                raise KeyError(
                    f"Unknown mission: session_id={session_id!r}, task_id={task_id!r}"
                )
            if row["status"] != "active":
                raise ValueError(
                    f"Cannot complete mission with status {row['status']!r}; expected 'active'."
                )
            if notes is None:
                conn.execute(
                    "UPDATE missions SET status='completed', completed_at=?, updated_at=? WHERE session_id=? AND task_id=?",
                    (now, now, session_id, task_id),
                )
            else:
                existing_notes = json.loads(row["notes"])
                merged_notes = {**existing_notes, **notes}
                conn.execute(
                    "UPDATE missions SET status='completed', completed_at=?, updated_at=?, notes=? WHERE session_id=? AND task_id=?",
                    (now, now, canonical_json(merged_notes), session_id, task_id),
                )
        return self.get_mission(session_id, task_id)

    def update_mission_notes(self, session_id: str, task_id: str, notes: dict[str, Any]) -> MissionRecord:
        now = utc_now()
        with closing(self._connect()) as conn, conn:
            conn.execute(
                "UPDATE missions SET notes=?, updated_at=? WHERE session_id=? AND task_id=?",
                (canonical_json(notes), now, session_id, task_id),
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

    def latest_stuck_attempt_id(self, session_id: str, task_id: str) -> int:
        with closing(self._connect()) as conn, conn:
            row = conn.execute(
                "SELECT MAX(attempt_id) AS latest_id FROM stuck_attempts WHERE session_id=? AND task_id=?",
                (session_id, task_id),
            ).fetchone()
        if not row or row["latest_id"] is None:
            return 0
        return int(row["latest_id"])

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

    def create_subagent_span(
        self,
        session_id: str,
        task_id: str,
        values: dict[str, Any],
    ) -> SubagentSpanRecord:
        now = utc_now()
        child_span_id = f"child_{secrets.token_urlsafe(12)}"
        with closing(self._connect()) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            host_child_id = values["host_child_id"]
            if host_child_id:
                existing = conn.execute(
                    """
                    SELECT child_span_id FROM subagent_spans
                    WHERE session_id=? AND task_id=? AND host=? AND host_child_id=?
                    LIMIT 1
                    """,
                    (session_id, task_id, values["host"], host_child_id),
                ).fetchone()
                if existing is not None:
                    raise ValueError(
                        f"host_child_id {host_child_id!r} is already registered for this mission and host."
                    )
            row = conn.execute(
                "SELECT COALESCE(MAX(seq), 0) AS seq FROM receipts WHERE session_id=?",
                (session_id,),
            ).fetchone()
            conn.execute(
                """
                INSERT INTO subagent_spans(child_span_id, session_id, task_id, host, subagent_type,
                                           host_child_id, context_mode, workspace_kind, status,
                                           delegated_scope, delegated_budget, budget_consumed,
                                           started_at, ended_at, transcript_ref, artifact_refs,
                    last_message, parent_receipt_seq, terminal_receipt_seq)
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, 'running', ?, ?, ?, ?, NULL, '', ?, '', ?, 0)
                """,
                (
                    child_span_id,
                    session_id,
                    task_id,
                    values["host"],
                    values["subagent_type"],
                    host_child_id,
                    values["context_mode"],
                    values["workspace_kind"],
                    values["delegated_scope"],
                    canonical_json(values["delegated_budget"]),
                    canonical_json({}),
                    now,
                    canonical_json([]),
                    int(row["seq"] if row else 0),
                ),
            )
        return self.get_subagent_span(session_id, task_id, child_span_id)

    def get_subagent_span(
        self, session_id: str, task_id: str, child_span_id: str
    ) -> SubagentSpanRecord:
        with closing(self._connect()) as conn, conn:
            row = conn.execute(
                "SELECT * FROM subagent_spans WHERE session_id=? AND task_id=? AND child_span_id=?",
                (session_id, task_id, child_span_id),
            ).fetchone()
        if row is None:
            raise KeyError(f"Unknown child_span_id: {child_span_id!r}")
        return self._row_to_subagent_span(row)

    def list_subagent_spans(
        self, session_id: str, task_id: str
    ) -> list[SubagentSpanRecord]:
        with closing(self._connect()) as conn, conn:
            rows = conn.execute(
                "SELECT * FROM subagent_spans WHERE session_id=? AND task_id=? ORDER BY started_at ASC",
                (session_id, task_id),
            ).fetchall()
        return [self._row_to_subagent_span(row) for row in rows]

    def stop_subagent_span(
        self,
        session_id: str,
        task_id: str,
        child_span_id: str,
        values: dict[str, Any],
    ) -> SubagentSpanRecord:
        now = utc_now()
        with closing(self._connect()) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute(
                "SELECT status FROM subagent_spans WHERE session_id=? AND task_id=? AND child_span_id=?",
                (session_id, task_id, child_span_id),
            ).fetchone()
            if existing is None:
                raise KeyError(f"Unknown child_span_id: {child_span_id!r}")
            if existing["status"] in SUBAGENT_TERMINAL_STATUSES:
                raise ValueError(
                    f"child_span_id {child_span_id!r} is already terminal with status {existing['status']!r}."
                )
            conn.execute(
                """
                UPDATE subagent_spans
                SET status=?, budget_consumed=?, ended_at=?, transcript_ref=?, artifact_refs=?, last_message=?,
                    terminal_receipt_seq=(SELECT COALESCE(MAX(seq), 0) FROM receipts WHERE session_id=?)
                WHERE session_id=? AND task_id=? AND child_span_id=?
                """,
                (
                    values["status"],
                    canonical_json(values["budget_consumed"]),
                    now,
                    values["transcript_ref"],
                    canonical_json(values["artifact_refs"]),
                    values["last_message"],
                    session_id,
                    session_id,
                    task_id,
                    child_span_id,
                ),
            )
        return self.get_subagent_span(session_id, task_id, child_span_id)

    def record_subagent_handoff(
        self,
        child_span_id: str,
        session_id: str,
        task_id: str,
        values: dict[str, Any],
    ) -> SubagentHandoffRecord:
        now = utc_now()
        with closing(self._connect()) as conn, conn:
            cur = conn.execute(
                """
                INSERT INTO subagent_handoffs(child_span_id, session_id, task_id, summary,
                                              verified_claims, receipt_ids, risks,
                                              unverified_items, created_at)
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    child_span_id,
                    session_id,
                    task_id,
                    values["summary"],
                    canonical_json(values["verified_claims"]),
                    canonical_json(values["receipt_ids"]),
                    canonical_json(values["risks"]),
                    canonical_json(values["unverified_items"]),
                    now,
                ),
            )
            handoff_id = int(cur.lastrowid)
        return SubagentHandoffRecord(
            handoff_id=handoff_id,
            child_span_id=child_span_id,
            session_id=session_id,
            task_id=task_id,
            summary=values["summary"],
            verified_claims=values["verified_claims"],
            receipt_ids=values["receipt_ids"],
            risks=values["risks"],
            unverified_items=values["unverified_items"],
            created_at=now,
        )

    def list_subagent_handoffs(
        self, session_id: str, task_id: str, child_span_id: str | None = None
    ) -> list[SubagentHandoffRecord]:
        query = "SELECT * FROM subagent_handoffs WHERE session_id=? AND task_id=?"
        params: list[Any] = [session_id, task_id]
        if child_span_id:
            query += " AND child_span_id=?"
            params.append(child_span_id)
        query += " ORDER BY created_at ASC"
        with closing(self._connect()) as conn, conn:
            rows = conn.execute(query, params).fetchall()
        return [self._row_to_subagent_handoff(row) for row in rows]

    def _row_to_subagent_span(self, row: sqlite3.Row) -> SubagentSpanRecord:
        return SubagentSpanRecord(
            child_span_id=row["child_span_id"],
            session_id=row["session_id"],
            task_id=row["task_id"],
            host=row["host"],
            subagent_type=row["subagent_type"],
            host_child_id=row["host_child_id"],
            context_mode=row["context_mode"],
            workspace_kind=row["workspace_kind"],
            status=row["status"],
            delegated_scope=row["delegated_scope"],
            delegated_budget=json.loads(row["delegated_budget"]),
            budget_consumed=json.loads(row["budget_consumed"]),
            started_at=row["started_at"],
            ended_at=row["ended_at"],
            transcript_ref=row["transcript_ref"],
            artifact_refs=json.loads(row["artifact_refs"]),
            last_message=row["last_message"],
            parent_receipt_seq=int(row["parent_receipt_seq"]),
            terminal_receipt_seq=int(row["terminal_receipt_seq"]),
        )

    def _row_to_subagent_handoff(self, row: sqlite3.Row) -> SubagentHandoffRecord:
        return SubagentHandoffRecord(
            handoff_id=int(row["handoff_id"]),
            child_span_id=row["child_span_id"],
            session_id=row["session_id"],
            task_id=row["task_id"],
            summary=row["summary"],
            verified_claims=json.loads(row["verified_claims"]),
            receipt_ids=json.loads(row["receipt_ids"]),
            risks=json.loads(row["risks"]),
            unverified_items=json.loads(row["unverified_items"]),
            created_at=row["created_at"],
        )

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

    def _receipt_from_row(self, row: sqlite3.Row) -> ReceiptRecord:
        return ReceiptRecord(
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
        if not hmac.compare_digest(
            signature, computed_signature
        ) or not hmac.compare_digest(receipt_id, computed_receipt_id):
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
                "SELECT * FROM receipts WHERE receipt_id=?",
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
                receipt = ReceiptRecord(
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
            else:
                receipt = self._receipt_from_row(existing)
                if not hmac.compare_digest(
                    receipt.signature, signature
                ) or not self.verify_receipt(receipt):
                    raise ValueError("Existing receipt_id row mismatch")
            conn.commit()
        return receipt

    def get_receipts(
        self,
        receipt_ids: Iterable[str],
        session_id: str | None = None,
        task_id: str | None | _UnsetTaskId = _TASK_ID_UNSET,
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
        if task_id is None:
            query += " AND task_id IS NULL"
        elif task_id is not _TASK_ID_UNSET:
            query += " AND task_id=?"
            params.append(task_id)
        with closing(self._connect()) as conn, conn:
            rows = conn.execute(query, params).fetchall()
        return [self._receipt_from_row(row) for row in rows]

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
        return [self._receipt_from_row(row) for row in rows]

    def latest_receipt_seq(self, session_id: str, task_id: str | None = None) -> int:
        query = "SELECT COALESCE(MAX(seq), 0) AS seq FROM receipts WHERE session_id=?"
        params: list[Any] = [session_id]
        if task_id:
            query += " AND task_id=?"
            params.append(task_id)
        with closing(self._connect()) as conn, conn:
            row = conn.execute(query, params).fetchone()
        return int(row["seq"])

    def _approval_freshness_receipt_is_gate_echo(
        self, receipt: ReceiptRecord, task_id: str, gate_type: str
    ) -> bool:
        if receipt.task_id != task_id:
            return False
        if receipt.tool_name != f"agent-runway_{gate_type}":
            return False
        return receipt.metadata.get("gate_type") == gate_type

    def _has_freshness_relevant_receipt_after(
        self, approval: ApprovalRecord, session_id: str, task_id: str
    ) -> bool:
        with closing(self._connect()) as conn, conn:
            rows = conn.execute(
                """
                SELECT * FROM receipts
                WHERE session_id=? AND seq>?
                ORDER BY seq ASC
                """,
                (session_id, approval.after_receipt_seq),
            ).fetchall()
        for row in rows:
            receipt = self._receipt_from_row(row)
            if self._approval_freshness_receipt_is_gate_echo(
                receipt, task_id, approval.gate_type
            ):
                continue
            return True
        return False

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
        ttl_seconds: int | None = 600,
        meta: dict[str, Any] | None = None,
    ) -> ApprovalRecord:
        created_at = utc_now()
        approval_meta = meta or {}
        if ttl_seconds is None and approval_meta.get("authorization_kind") != "standing_boundary":
            raise ValueError("ttl_seconds=None requires standing_boundary authorization_kind.")
        expires_at = "never" if ttl_seconds is None else self._expiry_from_ttl(ttl_seconds)
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
                    canonical_json(approval_meta),
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
            approval_meta,
        )

    def _expiry_from_ttl(self, ttl_seconds: int) -> str:
        return (
            (datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds))
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z")
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
        
        Design note: freshness is session-scoped, with one narrow exception for host
        post-tool receipts that merely echo the same approved gate call. This keeps
        later task activity from silently reusing stale approvals while avoiding a
        self-invalidating Stop hook immediately after the gate tool records its own
        post-tool receipt.
        """
        if approval is None or not approval.approved:
            return False
        latest = self.latest_approval(session_id, task_id, approval.gate_type)
        if latest is None or latest.token != approval.token:
            return False
        if approval.meta.get("authorization_kind") == "standing_boundary":
            return approval.expires_at == "never"
        if approval.gate_type == "turn_end_gate":
            try:
                approved_stuck_attempt_id = int(
                    approval.meta.get("latest_stuck_attempt_id") or 0
                )
            except (TypeError, ValueError):
                approved_stuck_attempt_id = 0
            if approved_stuck_attempt_id < self.latest_stuck_attempt_id(session_id, task_id):
                return False
        expires = datetime.fromisoformat(approval.expires_at.replace("Z", "+00:00"))
        if expires < datetime.now(timezone.utc):
            return False
        latest_receipt_seq = self.latest_receipt_seq(session_id)
        if approval.after_receipt_seq >= latest_receipt_seq:
            return True
        return not self._has_freshness_relevant_receipt_after(
            approval, session_id, task_id
        )
