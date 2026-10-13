"""Database manager — SQLite (tests) and MySQL (production).

Amendment 4: NO INSERT IGNORE.
  - Idempotent success ONLY when vote_id AND content are identical.
  - Conflicting same-client_id vote is rejected and logged.
  - All constraint checks happen under a lock for atomicity.

Amendment 5: Tests use per-node temporary SQLite FILES, not shared in-memory DBs.
Amendment 8: MySQL health-check helper for the smoke test.
"""

import json
import logging
import sqlite3
import threading
import time
from typing import Optional

from node.models import InsertResult, VoteRecord, VoteStatus, SyncLogEntry

logger = logging.getLogger(__name__)


class DatabaseManager:
    """Thin abstraction over SQLite / MySQL for the votes, sync_log, and election_log tables."""

    def __init__(
        self,
        use_sqlite: bool = True,
        sqlite_path: Optional[str] = None,
        mysql_config: Optional[dict] = None,
    ) -> None:
        self._use_sqlite = use_sqlite
        self._sqlite_path = sqlite_path      # None ⇒ ":memory:" (only for quick one-off tests)
        self._mysql_config = mysql_config or {}
        self._conn = None
        self._lock = threading.Lock()

    # ── Lifecycle ────────────────────────────────────────────────

    def initialize(self) -> None:
        """Open connection and create tables if they don't exist."""
        if self._use_sqlite:
            path = self._sqlite_path or ":memory:"
            self._conn = sqlite3.connect(path, check_same_thread=False)
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
            self._create_tables_sqlite()
        else:
            import mysql.connector
            max_attempts = 20
            for attempt in range(1, max_attempts + 1):
                try:
                    self._conn = mysql.connector.connect(**self._mysql_config)
                    self._conn.autocommit = False
                    self._create_tables_mysql()
                    break
                except Exception as e:
                    if attempt == max_attempts:
                        logger.error("Failed to connect to MySQL after %d attempts: %s", max_attempts, e)
                        raise
                    logger.info("Waiting for MySQL connection (%d/%d): %s", attempt, max_attempts, e)
                    time.sleep(1.0)

    def close(self) -> None:
        with self._lock:
            if self._conn:
                try:
                    self._conn.close()
                except Exception:
                    pass
                self._conn = None

    # ── Schema creation ──────────────────────────────────────────

    def _create_tables_sqlite(self) -> None:
        c = self._conn.cursor()
        c.execute("""
            CREATE TABLE IF NOT EXISTS votes (
                vote_id         TEXT    NOT NULL PRIMARY KEY,
                client_id       TEXT    NOT NULL UNIQUE,
                origin_node_id  INTEGER NOT NULL,
                lamport_ts      INTEGER NOT NULL,
                choice          TEXT    NOT NULL,
                received_at_ms  INTEGER NOT NULL,
                status          TEXT    NOT NULL DEFAULT 'PENDING'
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS election_log (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type      TEXT    NOT NULL,
                node_id         INTEGER NOT NULL,
                lamport_ts      INTEGER NOT NULL,
                election_term   INTEGER DEFAULT 0,
                initiator_id    INTEGER DEFAULT 0,
                details         TEXT,
                logged_at_ms    INTEGER NOT NULL
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS sync_log (
                entry_id        INTEGER PRIMARY KEY AUTOINCREMENT,
                entry_type      TEXT    NOT NULL,
                vote_id         TEXT,
                client_id       TEXT,
                origin_node_id  INTEGER,
                lamport_ts      INTEGER NOT NULL,
                choice          TEXT,
                status          TEXT,
                details         TEXT,
                created_at_ms   INTEGER NOT NULL
            )
        """)
        try:
            c.execute("ALTER TABLE votes ADD COLUMN status TEXT NOT NULL DEFAULT 'PENDING'")
        except Exception:
            pass
        self._conn.commit()

    def _create_tables_mysql(self) -> None:
        c = self._conn.cursor()
        c.execute("""
            CREATE TABLE IF NOT EXISTS votes (
                vote_id         VARCHAR(128)  NOT NULL,
                client_id       VARCHAR(64)   NOT NULL,
                origin_node_id  INT           NOT NULL,
                lamport_ts      BIGINT        NOT NULL,
                choice          VARCHAR(100)  NOT NULL,
                received_at_ms  BIGINT        NOT NULL,
                status          VARCHAR(16)   NOT NULL DEFAULT 'PENDING',
                PRIMARY KEY (vote_id),
                UNIQUE KEY uk_client_id (client_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS election_log (
                id              INT    AUTO_INCREMENT PRIMARY KEY,
                event_type      VARCHAR(40)  NOT NULL,
                node_id         INT          NOT NULL,
                lamport_ts      BIGINT       NOT NULL,
                election_term   BIGINT       DEFAULT 0,
                initiator_id    INT          DEFAULT 0,
                details         JSON,
                logged_at_ms    BIGINT       NOT NULL
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS sync_log (
                entry_id        INT           AUTO_INCREMENT PRIMARY KEY,
                entry_type      VARCHAR(40)   NOT NULL,
                vote_id         VARCHAR(128),
                client_id       VARCHAR(64),
                origin_node_id  INT,
                lamport_ts      BIGINT        NOT NULL,
                choice          VARCHAR(100),
                status          VARCHAR(16),
                details         TEXT,
                created_at_ms   BIGINT        NOT NULL
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)
        try:
            c.execute("ALTER TABLE votes ADD COLUMN status VARCHAR(16) NOT NULL DEFAULT 'PENDING'")
        except Exception:
            pass
        self._conn.commit()

    # ── Internal helpers ─────────────────────────────────────────

    def _ph(self, sql: str) -> str:
        """Replace ? placeholders with %s for MySQL."""
        if not self._use_sqlite:
            return sql.replace("?", "%s")
        return sql

    def _row_to_vote(self, row: tuple) -> VoteRecord:
        status = row[6] if len(row) > 6 else VoteStatus.COMMITTED.value
        return VoteRecord(
            vote_id=row[0],
            client_id=row[1],
            origin_node_id=int(row[2]),
            lamport_ts=int(row[3]),
            choice=row[4],
            received_at_ms=int(row[5]),
            status=status,
        )

    # ── Vote operations (all under self._lock) ───────────────────

    def insert_vote(self, vote: VoteRecord) -> InsertResult:
        """Insert a vote with amendment-4 duplicate handling + lifecycle states.

        1. vote_id already exists, content identical  → IDEMPOTENT
        2. vote_id already exists, content differs    → VOTE_ID_CONFLICT (bug)
        3. client_id already exists:
           - if existing status == PENDING and choice matches → PENDING_RETRY
           - if existing status == PENDING and choice differs → PENDING_CONFLICT
           - if existing status == COMMITTED                  → CLIENT_ALREADY_VOTED
        4. Otherwise                                  → INSERTED
        """
        with self._lock:
            cur = self._conn.cursor()

            # ── Check vote_id ────────────────────────────────────
            cur.execute(self._ph(
                "SELECT vote_id, client_id, origin_node_id, lamport_ts, choice, received_at_ms, status "
                "FROM votes WHERE vote_id = ?"
            ), (vote.vote_id,))
            existing_row = cur.fetchone()

            if existing_row is not None:
                existing = self._row_to_vote(existing_row)
                if existing.content_matches(vote):
                    return InsertResult.IDEMPOTENT
                logger.error(
                    "VOTE_ID_CONFLICT: vote_id=%s exists with different content. "
                    "existing=%s new=%s",
                    vote.vote_id, existing, vote,
                )
                return InsertResult.VOTE_ID_CONFLICT

            # ── Check client_id ──────────────────────────────────
            cur.execute(self._ph(
                "SELECT vote_id, client_id, origin_node_id, lamport_ts, choice, received_at_ms, status "
                "FROM votes WHERE client_id = ?"
            ), (vote.client_id,))
            client_row = cur.fetchone()

            if client_row is not None:
                client_vote = self._row_to_vote(client_row)
                if client_vote.status == VoteStatus.PENDING.value:
                    if client_vote.choice == vote.choice:
                        logger.info(
                            "PENDING_RETRY: client_id=%s retrying pending vote_id=%s with same choice=%s",
                            vote.client_id, client_vote.vote_id, vote.choice,
                        )
                        return InsertResult.PENDING_RETRY
                    else:
                        logger.warning(
                            "PENDING_CONFLICT: client_id=%s has pending vote with different choice (existing=%s, new=%s)",
                            vote.client_id, client_vote.choice, vote.choice,
                        )
                        return InsertResult.PENDING_CONFLICT
                else:
                    logger.warning(
                        "CLIENT_ALREADY_VOTED: client_id=%s already has committed vote_id=%s",
                        vote.client_id, client_row[0],
                    )
                    return InsertResult.CLIENT_ALREADY_VOTED

            # ── Insert ───────────────────────────────────────────
            status = vote.status or VoteStatus.PENDING.value
            cur.execute(self._ph(
                "INSERT INTO votes "
                "(vote_id, client_id, origin_node_id, lamport_ts, choice, received_at_ms, status) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)"
            ), (
                vote.vote_id,
                vote.client_id,
                vote.origin_node_id,
                vote.lamport_ts,
                vote.choice,
                vote.received_at_ms,
                status,
            ))
            self._append_sync_log_locked(
                entry_type="VOTE_INSERTED",
                vote_id=vote.vote_id,
                client_id=vote.client_id,
                origin_node_id=vote.origin_node_id,
                lamport_ts=vote.lamport_ts,
                choice=vote.choice,
                status=status,
            )
            self._conn.commit()
            return InsertResult.INSERTED

    def finalize_vote(self, vote_id: str) -> bool:
        """Mark a pending vote as COMMITTED.

        Returns True if the vote was marked COMMITTED or was already COMMITTED (idempotent).
        Returns False if the vote_id does not exist.
        """
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(self._ph(
                "SELECT status, client_id, origin_node_id, lamport_ts, choice FROM votes WHERE vote_id = ?"
            ), (vote_id,))
            row = cur.fetchone()
            if row is None:
                return False
            status = row[0]
            if status == VoteStatus.COMMITTED.value:
                return True
            cur.execute(self._ph(
                "UPDATE votes SET status = ? WHERE vote_id = ?"
            ), (VoteStatus.COMMITTED.value, vote_id))
            self._append_sync_log_locked(
                entry_type="VOTE_FINALIZED",
                vote_id=vote_id,
                client_id=row[1],
                origin_node_id=row[2],
                lamport_ts=row[3],
                choice=row[4],
                status=VoteStatus.COMMITTED.value,
            )
            self._conn.commit()
            return True

    def demote_vote(self, vote_id: str, new_status: str = "PENDING", reason: str = "") -> bool:
        """Demote an unauthoritative or ghost vote to PENDING.

        Returns True if the vote was demoted, or False if vote_id does not exist.
        """
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(self._ph(
                "SELECT status, client_id, origin_node_id, lamport_ts, choice FROM votes WHERE vote_id = ?"
            ), (vote_id,))
            row = cur.fetchone()
            if row is None:
                return False
            cur.execute(self._ph(
                "UPDATE votes SET status = ? WHERE vote_id = ?"
            ), (new_status, vote_id))
            self._append_sync_log_locked(
                entry_type="VOTE_DEMOTED",
                vote_id=vote_id,
                client_id=row[1],
                origin_node_id=row[2],
                lamport_ts=row[3],
                choice=row[4],
                status=new_status,
                details={"previous_status": row[0], "reason": reason or "unauthoritative_partial_finalization"},
            )
            self._conn.commit()
            return True

    def get_vote_by_id(self, vote_id: str) -> Optional[VoteRecord]:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(self._ph(
                "SELECT vote_id, client_id, origin_node_id, lamport_ts, choice, received_at_ms, status "
                "FROM votes WHERE vote_id = ?"
            ), (vote_id,))
            row = cur.fetchone()
            return self._row_to_vote(row) if row else None

    def get_vote_by_client_id(self, client_id: str) -> Optional[VoteRecord]:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(self._ph(
                "SELECT vote_id, client_id, origin_node_id, lamport_ts, choice, received_at_ms, status "
                "FROM votes WHERE client_id = ?"
            ), (client_id,))
            row = cur.fetchone()
            return self._row_to_vote(row) if row else None

    def get_all_votes(self, committed_only: bool = True) -> list:
        """Return all votes, sorted by merge_key for deterministic ordering.

        Defaults to returning ONLY COMMITTED votes (committed_only=True) so that
        recovery and synchronization never unintentionally include pending records.
        """
        with self._lock:
            cur = self._conn.cursor()
            if committed_only:
                cur.execute(self._ph(
                    "SELECT vote_id, client_id, origin_node_id, lamport_ts, choice, received_at_ms, status "
                    "FROM votes WHERE status = ? ORDER BY lamport_ts, origin_node_id, vote_id"
                ), (VoteStatus.COMMITTED.value,))
            else:
                cur.execute(self._ph(
                    "SELECT vote_id, client_id, origin_node_id, lamport_ts, choice, received_at_ms, status "
                    "FROM votes ORDER BY lamport_ts, origin_node_id, vote_id"
                ))
            return [self._row_to_vote(row) for row in cur.fetchall()]

    def get_all_votes_including_pending(self) -> list:
        """Diagnostic method: Return all votes including PENDING records."""
        return self.get_all_votes(committed_only=False)

    def get_tally(self) -> dict:
        """Return {choice: count} for all COMMITTED votes."""
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(self._ph(
                "SELECT choice, COUNT(*) FROM votes WHERE status = ? GROUP BY choice"
            ), (VoteStatus.COMMITTED.value,))
            return {row[0]: int(row[1]) for row in cur.fetchall()}

    def count_votes(self, status: Optional[str] = VoteStatus.COMMITTED.value) -> int:
        """Count votes matching status (defaults to COMMITTED). If status is None, count all."""
        with self._lock:
            cur = self._conn.cursor()
            if status is not None:
                cur.execute(self._ph("SELECT COUNT(*) FROM votes WHERE status = ?"), (status,))
            else:
                cur.execute("SELECT COUNT(*) FROM votes")
            row = cur.fetchone()
            return int(row[0]) if row else 0

    def delete_vote(self, vote_id: str) -> bool:
        """Remove a vote by ID."""
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(self._ph("DELETE FROM votes WHERE vote_id = ?"), (vote_id,))
            self._conn.commit()
            return cur.rowcount > 0

    # ── Election log ─────────────────────────────────────────────

    def log_election_event(
        self,
        event_type: str,
        node_id: int,
        lamport_ts: int,
        election_term: int = 0,
        initiator_id: int = 0,
        details: Optional[dict] = None,
    ) -> None:
        with self._lock:
            if not self._conn:
                return
            cur = self._conn.cursor()
            cur.execute(self._ph(
                "INSERT INTO election_log "
                "(event_type, node_id, lamport_ts, election_term, initiator_id, details, logged_at_ms) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)"
            ), (
                event_type,
                node_id,
                lamport_ts,
                election_term,
                initiator_id,
                json.dumps(details) if details else None,
                int(time.time() * 1000),
            ))
            self._conn.commit()

    def get_election_events(self, event_type: Optional[str] = None) -> list[dict]:
        with self._lock:
            if not self._conn:
                return []
            cur = self._conn.cursor()
            if event_type:
                cur.execute(self._ph(
                    "SELECT id, event_type, node_id, lamport_ts, election_term, initiator_id, details, logged_at_ms "
                    "FROM election_log WHERE event_type = ? ORDER BY id ASC"
                ), (event_type,))
            else:
                cur.execute(
                    "SELECT id, event_type, node_id, lamport_ts, election_term, initiator_id, details, logged_at_ms "
                    "FROM election_log ORDER BY id ASC"
                )
            rows = cur.fetchall()
            events = []
            for row in rows:
                details = None
                if row[6]:
                    try:
                        details = json.loads(row[6]) if isinstance(row[6], str) else row[6]
                    except Exception:
                        details = row[6]
                events.append({
                    "id": row[0],
                    "event_type": row[1],
                    "node_id": row[2],
                    "lamport_ts": row[3],
                    "election_term": row[4],
                    "initiator_id": row[5],
                    "details": details,
                    "logged_at_ms": row[7],
                })
            return events

    # ── Sync log and state recovery (Phase 4) ────────────────────

    def _append_sync_log_locked(
        self,
        entry_type: str,
        vote_id: Optional[str] = None,
        client_id: Optional[str] = None,
        origin_node_id: Optional[int] = None,
        lamport_ts: int = 0,
        choice: Optional[str] = None,
        status: Optional[str] = None,
        details: Optional[dict | str] = None,
    ) -> int:
        if not self._conn:
            return 0
        cur = self._conn.cursor()
        details_str = json.dumps(details) if isinstance(details, dict) else (details or "")
        created_at_ms = int(time.time() * 1000)
        cur.execute(self._ph(
            "INSERT INTO sync_log "
            "(entry_type, vote_id, client_id, origin_node_id, lamport_ts, choice, status, details, created_at_ms) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"
        ), (
            entry_type,
            vote_id,
            client_id,
            origin_node_id,
            lamport_ts,
            choice,
            status,
            details_str,
            created_at_ms,
        ))
        return cur.lastrowid or 0

    def append_sync_log(
        self,
        entry_type: str | SyncLogEntry,
        vote_id: Optional[str] = None,
        client_id: Optional[str] = None,
        origin_node_id: Optional[int] = None,
        lamport_ts: int = 0,
        choice: Optional[str] = None,
        status: Optional[str] = None,
        details: Optional[dict | str] = None,
    ) -> int:
        if isinstance(entry_type, SyncLogEntry):
            entry = entry_type
            entry_type = entry.entry_type
            vote_id = entry.vote_id
            client_id = entry.client_id
            origin_node_id = entry.origin_node_id
            lamport_ts = entry.lamport_ts
            choice = entry.choice
            status = entry.status
            details = entry.details

        with self._lock:
            lid = self._append_sync_log_locked(
                entry_type, vote_id, client_id, origin_node_id, lamport_ts, choice, status, details
            )
            self._conn.commit()
            return lid

    def get_sync_log(
        self,
        since_entry_id: int = 0,
        entry_type: Optional[str] = None,
        vote_id: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> list[SyncLogEntry]:
        with self._lock:
            if not self._conn:
                return []
            cur = self._conn.cursor()
            clauses = ["entry_id > ?"]
            params = [since_entry_id]
            if entry_type:
                clauses.append("entry_type = ?")
                params.append(entry_type)
            if vote_id:
                clauses.append("vote_id = ?")
                params.append(vote_id)

            where_str = " AND ".join(clauses)
            query = (
                "SELECT entry_id, entry_type, vote_id, client_id, origin_node_id, "
                "lamport_ts, choice, status, details, created_at_ms FROM sync_log "
                f"WHERE {where_str} ORDER BY entry_id ASC"
            )
            if limit:
                query += f" LIMIT {int(limit)}"
            cur.execute(self._ph(query), tuple(params))
            entries = []
            for row in cur.fetchall():
                entries.append(SyncLogEntry(
                    entry_id=row[0],
                    entry_type=row[1],
                    vote_id=row[2],
                    client_id=row[3],
                    origin_node_id=int(row[4]) if row[4] is not None else None,
                    lamport_ts=int(row[5]),
                    choice=row[6],
                    status=row[7],
                    details=row[8],
                    created_at_ms=int(row[9]),
                ))
            return entries

    def get_max_lamport_ts(self) -> int:
        """Find the maximum Lamport timestamp across votes, sync_log, and election_log."""
        with self._lock:
            if not self._conn:
                return 0
            cur = self._conn.cursor()
            max_ts = 0
            for table in ("votes", "sync_log", "election_log"):
                try:
                    cur.execute(f"SELECT MAX(lamport_ts) FROM {table}")
                    row = cur.fetchone()
                    if row and row[0] is not None:
                        max_ts = max(max_ts, int(row[0]))
                except Exception:
                    pass
            return max_ts

    def replay_sync_log(self) -> dict:
        """Replay durable sync log and votes to verify state and restore in-memory invariants."""
        with self._lock:
            if not self._conn:
                return {"sync_log_entries": 0, "committed_votes": 0, "pending_votes": 0, "max_lamport_ts": 0}
            cur = self._conn.cursor()
            cur.execute("SELECT COUNT(*) FROM sync_log")
            sync_count = int(cur.fetchone()[0])

            cur.execute(self._ph("SELECT COUNT(*) FROM votes WHERE status = ?"), (VoteStatus.COMMITTED.value,))
            committed_count = int(cur.fetchone()[0])

            cur.execute(self._ph("SELECT COUNT(*) FROM votes WHERE status = ?"), (VoteStatus.PENDING.value,))
            pending_count = int(cur.fetchone()[0])

            max_ts = 0
            for table in ("votes", "sync_log", "election_log"):
                try:
                    cur.execute(f"SELECT MAX(lamport_ts) FROM {table}")
                    row = cur.fetchone()
                    if row and row[0] is not None:
                        max_ts = max(max_ts, int(row[0]))
                except Exception:
                    pass

            return {
                "sync_log_entries": sync_count,
                "committed_votes": committed_count,
                "pending_votes": pending_count,
                "max_lamport_ts": max_ts,
            }

    def insert_synced_vote(self, vote: VoteRecord) -> InsertResult:
        """Idempotently insert or promote an authoritative vote received during SyncLog synchronization."""
        with self._lock:
            cur = self._conn.cursor()
            # 1. Check by vote_id
            cur.execute(self._ph(
                "SELECT vote_id, client_id, origin_node_id, lamport_ts, choice, received_at_ms, status "
                "FROM votes WHERE vote_id = ?"
            ), (vote.vote_id,))
            row = cur.fetchone()
            if row is not None:
                existing = self._row_to_vote(row)
                if not existing.content_matches(vote):
                    return InsertResult.VOTE_ID_CONFLICT
                if existing.status == VoteStatus.COMMITTED.value:
                    return InsertResult.IDEMPOTENT
                # Promote existing PENDING to COMMITTED
                cur.execute(self._ph(
                    "UPDATE votes SET status = ? WHERE vote_id = ?"
                ), (VoteStatus.COMMITTED.value, vote.vote_id))
                self._append_sync_log_locked(
                    entry_type="SYNC_PROMOTED",
                    vote_id=vote.vote_id,
                    client_id=vote.client_id,
                    origin_node_id=vote.origin_node_id,
                    lamport_ts=vote.lamport_ts,
                    choice=vote.choice,
                    status=VoteStatus.COMMITTED.value,
                )
                self._conn.commit()
                return InsertResult.INSERTED

            # 2. Check by client_id
            cur.execute(self._ph(
                "SELECT vote_id, client_id, origin_node_id, lamport_ts, choice, received_at_ms, status "
                "FROM votes WHERE client_id = ?"
            ), (vote.client_id,))
            client_row = cur.fetchone()
            if client_row is not None:
                client_vote = self._row_to_vote(client_row)
                if client_vote.choice == vote.choice:
                    if client_vote.status == VoteStatus.COMMITTED.value:
                        return InsertResult.IDEMPOTENT
                    cur.execute(self._ph(
                        "UPDATE votes SET status = ? WHERE vote_id = ?"
                    ), (VoteStatus.COMMITTED.value, client_vote.vote_id))
                    self._append_sync_log_locked(
                        entry_type="SYNC_PROMOTED",
                        vote_id=client_vote.vote_id,
                        client_id=vote.client_id,
                        origin_node_id=client_vote.origin_node_id,
                        lamport_ts=vote.lamport_ts,
                        choice=vote.choice,
                        status=VoteStatus.COMMITTED.value,
                    )
                    self._conn.commit()
                    return InsertResult.INSERTED
                else:
                    # Choice conflict on same client
                    # Rule 1: Never overwrite an already COMMITTED vote
                    if client_vote.status == VoteStatus.COMMITTED.value:
                        self._append_sync_log_locked(
                            entry_type="CLIENT_ID_CONFLICT",
                            vote_id=vote.vote_id,
                            client_id=vote.client_id,
                            origin_node_id=vote.origin_node_id,
                            lamport_ts=vote.lamport_ts,
                            choice=vote.choice,
                            status="REJECTED",
                            details={
                                "existing_vote_id": client_vote.vote_id,
                                "existing_choice": client_vote.choice,
                                "reason": "existing_committed_vote_preserved",
                            },
                        )
                        self._conn.commit()
                        return InsertResult.CLIENT_ALREADY_VOTED

                    # Rule 2: Both pending: deterministic winner rule (lower merge_key wins)
                    if client_vote.merge_key <= vote.merge_key:
                        self._append_sync_log_locked(
                            entry_type="CLIENT_ID_CONFLICT",
                            vote_id=vote.vote_id,
                            client_id=vote.client_id,
                            origin_node_id=vote.origin_node_id,
                            lamport_ts=vote.lamport_ts,
                            choice=vote.choice,
                            status="REJECTED",
                            details={"existing_vote_id": client_vote.vote_id, "reason": "deterministic_loser"},
                        )
                        self._conn.commit()
                        return InsertResult.CLIENT_ALREADY_VOTED

                    # Incoming vote has lower merge_key: replace pending vote
                    cur.execute(self._ph("DELETE FROM votes WHERE vote_id = ?"), (client_vote.vote_id,))
                    self._append_sync_log_locked(
                        entry_type="CLIENT_ID_CONFLICT",
                        vote_id=client_vote.vote_id,
                        client_id=client_vote.client_id,
                        origin_node_id=client_vote.origin_node_id,
                        lamport_ts=client_vote.lamport_ts,
                        choice=client_vote.choice,
                        status="REPLACED",
                        details={"winner_vote_id": vote.vote_id, "reason": "deterministic_winner"},
                    )

            # 3. Insert as COMMITTED
            cur.execute(self._ph(
                "INSERT INTO votes "
                "(vote_id, client_id, origin_node_id, lamport_ts, choice, received_at_ms, status) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)"
            ), (
                vote.vote_id,
                vote.client_id,
                vote.origin_node_id,
                vote.lamport_ts,
                vote.choice,
                vote.received_at_ms,
                VoteStatus.COMMITTED.value,
            ))
            self._append_sync_log_locked(
                entry_type="SYNC_INSERTED",
                vote_id=vote.vote_id,
                client_id=vote.client_id,
                origin_node_id=vote.origin_node_id,
                lamport_ts=vote.lamport_ts,
                choice=vote.choice,
                status=VoteStatus.COMMITTED.value,
            )
            self._conn.commit()
            return InsertResult.INSERTED

    # ── MySQL health check (amendment 8) ─────────────────────────

    @staticmethod
    def mysql_health_check(
        host: str = "localhost",
        port: int = 3306,
        user: str = "root",
        password: str = "votingpass",
        timeout: int = 5,
    ) -> bool:
        """Return True if MySQL is reachable and responsive."""
        try:
            import mysql.connector
            conn = mysql.connector.connect(
                host=host, port=port, user=user, password=password,
                connection_timeout=timeout,
            )
            cur = conn.cursor()
            cur.execute("SELECT 1")
            cur.fetchone()
            conn.close()
            return True
        except Exception:
            return False
