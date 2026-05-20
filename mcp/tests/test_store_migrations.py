from __future__ import annotations

import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path


MCP_ROOT = Path(__file__).resolve().parents[1]
LEGACY_PRE_SUBAGENT_SCHEMA = """
CREATE TABLE sessions (
    session_id TEXT PRIMARY KEY,
    host TEXT NOT NULL,
    cwd TEXT NOT NULL,
    created_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL
);
CREATE TABLE missions (
    session_id TEXT NOT NULL,
    task_id TEXT PRIMARY KEY,
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
    meta TEXT NOT NULL
);
CREATE TABLE stuck_attempts (
    attempt_id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    strategy_fingerprint TEXT NOT NULL,
    summary TEXT NOT NULL,
    receipt_ids TEXT NOT NULL,
    created_at TEXT NOT NULL
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
    created_at TEXT NOT NULL
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
    created_at TEXT NOT NULL
);
"""

LEGACY_SUBAGENT_SCHEMA = """
CREATE TABLE sessions (
    session_id TEXT PRIMARY KEY,
    host TEXT NOT NULL,
    cwd TEXT NOT NULL,
    created_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL
);
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
CREATE TABLE receipts (
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
CREATE TABLE subagent_spans (
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
    FOREIGN KEY(session_id) REFERENCES sessions(session_id),
    FOREIGN KEY(session_id, task_id) REFERENCES missions(session_id, task_id)
);
"""


def seed_terminal_span_without_terminal_seq(db_path: Path) -> None:
    with closing(sqlite3.connect(db_path)) as conn, conn:
        conn.executescript(LEGACY_SUBAGENT_SCHEMA)
        conn.execute(
            """
            INSERT INTO sessions(session_id, host, cwd, created_at, last_seen_at)
            VALUES('s1', 'host', '.', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')
            """
        )
        conn.execute(
            """
            INSERT INTO missions(session_id, task_id, goal, scope_boundary, completion_criteria,
                                 red_lines, status, slice_count, retry_budget, slice_budget,
                                 created_at, updated_at, completed_at, notes)
            VALUES('s1', 't1', 'goal', '', '[]', '[]', 'active', 0, 3, 24,
                   '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z', NULL, '{}')
            """
        )
        conn.execute(
            """
            INSERT INTO receipts(receipt_id, session_id, task_id, source, tool_name, command_text,
                                 exit_code, metadata, created_at, seq, signature)
            VALUES('r1', 's1', 't1', 'test', 'Bash', 'child', 0, '{}', '2026-01-01T00:00:01Z', 1, 'sig'),
                  ('r2', 's1', 't1', 'test', 'Bash', 'stop', 0, '{}', '2026-01-01T00:00:03Z', 2, 'sig'),
                  ('r3', 's1', 't1', 'test', 'Bash', 'later', 0, '{}', '2026-01-01T00:00:05Z', 3, 'sig')
            """
        )
        conn.execute(
            """
            INSERT INTO subagent_spans(child_span_id, session_id, task_id, host, subagent_type,
                                       host_child_id, context_mode, workspace_kind, status,
                                       delegated_scope, delegated_budget, budget_consumed,
                                       started_at, ended_at, transcript_ref, artifact_refs,
                                       last_message, parent_receipt_seq)
            VALUES('child1', 's1', 't1', 'host', 'reviewer', '', 'fresh', 'local_sandbox',
                   'completed', 'scope', '{}', '{}', '2026-01-01T00:00:00Z',
                   '2026-01-01T00:00:03Z', '', '[]', '', 0)
            """
        )


class StoreMigrationTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        if str(MCP_ROOT) not in sys.path:
            sys.path.insert(0, str(MCP_ROOT))

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_store_migrates_pre_subagent_database_without_crashing(self) -> None:
        legacy_path = Path(self.temp_dir.name) / "legacy-state.db"
        with closing(sqlite3.connect(legacy_path)) as conn, conn:
            conn.executescript(LEGACY_PRE_SUBAGENT_SCHEMA)

        import agent_runway_runtime.store as store_module

        store_module.RuntimeStore(db_path=str(legacy_path), secret="x" * 64)
        with closing(sqlite3.connect(legacy_path)) as conn:
            columns = {
                row[1]
                for row in conn.execute("PRAGMA table_info(subagent_spans)").fetchall()
            }

        self.assertIn("terminal_receipt_seq", columns)

    def test_runtime_store_releases_connection_after_schema_initialization(self) -> None:
        db_path = Path(self.temp_dir.name) / "connection-release.db"
        import agent_runway_runtime.store as store_module

        store_module.RuntimeStore(db_path=str(db_path), secret="x" * 64)

        for path in [db_path, Path(str(db_path) + "-wal"), Path(str(db_path) + "-shm")]:
            path.unlink(missing_ok=True)

    def test_migrates_existing_terminal_spans_to_receipt_seq_at_or_before_stop(self) -> None:
        db_path = Path(self.temp_dir.name) / "legacy-subagent.db"
        seed_terminal_span_without_terminal_seq(db_path)
        import agent_runway_runtime.store as store_module

        store_module.RuntimeStore(db_path=str(db_path), secret="x" * 64)
        with closing(sqlite3.connect(db_path)) as conn:
            terminal_seq = conn.execute(
                "SELECT terminal_receipt_seq FROM subagent_spans WHERE child_span_id='child1'"
            ).fetchone()[0]

        self.assertEqual(terminal_seq, 2)

    def test_migrates_legacy_subagent_schema_to_host_child_unique_index(self) -> None:
        db_path = Path(self.temp_dir.name) / "legacy-subagent-index.db"
        seed_terminal_span_without_terminal_seq(db_path)
        import agent_runway_runtime.store as store_module

        store_module.RuntimeStore(db_path=str(db_path), secret="x" * 64)
        with closing(sqlite3.connect(db_path)) as conn:
            index_sql = conn.execute(
                """
                SELECT sql FROM sqlite_master
                WHERE type='index' AND name='idx_subagent_spans_host_child_unique'
                """
            ).fetchone()[0]
            duplicate_blank = conn.execute(
                """
                INSERT INTO subagent_spans(child_span_id, session_id, task_id, host, subagent_type,
                                           host_child_id, context_mode, workspace_kind, status,
                                           delegated_scope, delegated_budget, budget_consumed,
                                           started_at, ended_at, transcript_ref, artifact_refs,
                                           last_message, parent_receipt_seq, terminal_receipt_seq)
                VALUES('child2', 's1', 't1', 'host', 'reviewer', '', 'fresh', 'local_sandbox',
                       'running', 'scope', '{}', '{}', '2026-01-01T00:00:04Z',
                       NULL, '', '[]', '', 0, 0)
                """
            )
            blank_count = conn.execute(
                """
                SELECT COUNT(*) FROM subagent_spans
                WHERE session_id='s1' AND task_id='t1' AND host='host' AND host_child_id=''
                """
            ).fetchone()[0]
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute(
                    """
                    INSERT INTO subagent_spans(child_span_id, session_id, task_id, host, subagent_type,
                                               host_child_id, context_mode, workspace_kind, status,
                                               delegated_scope, delegated_budget, budget_consumed,
                                               started_at, ended_at, transcript_ref, artifact_refs,
                                               last_message, parent_receipt_seq, terminal_receipt_seq)
                    VALUES('child3', 's1', 't1', 'host', 'reviewer', 'same-child', 'fresh', 'local_sandbox',
                           'running', 'scope', '{}', '{}', '2026-01-01T00:00:05Z',
                           NULL, '', '[]', '', 0, 0)
                    """
                )
                conn.execute(
                    """
                    INSERT INTO subagent_spans(child_span_id, session_id, task_id, host, subagent_type,
                                               host_child_id, context_mode, workspace_kind, status,
                                               delegated_scope, delegated_budget, budget_consumed,
                                               started_at, ended_at, transcript_ref, artifact_refs,
                                               last_message, parent_receipt_seq, terminal_receipt_seq)
                    VALUES('child4', 's1', 't1', 'host', 'reviewer', 'same-child', 'fresh', 'local_sandbox',
                           'running', 'scope', '{}', '{}', '2026-01-01T00:00:06Z',
                           NULL, '', '[]', '', 0, 0)
                    """
                )

        self.assertIsNotNone(duplicate_blank)
        self.assertEqual(2, blank_count)
        self.assertIn("session_id, task_id, host, host_child_id", index_sql)
        self.assertIn("WHERE host_child_id<>''", index_sql)
