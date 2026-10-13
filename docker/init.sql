-- docker/init.sql
-- Applied once per MySQL container at first boot.
-- Mirrors the schema created by node/db.py for SQLite.

CREATE DATABASE IF NOT EXISTS voting_node;
USE voting_node;

-- ─── Vote storage ───────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS votes (
    vote_id         VARCHAR(128)   NOT NULL,
    client_id       VARCHAR(64)    NOT NULL,
    origin_node_id  INT            NOT NULL,
    lamport_ts      BIGINT         NOT NULL,
    choice          VARCHAR(100)   NOT NULL,
    received_at_ms  BIGINT         NOT NULL,
    status          VARCHAR(16)    NOT NULL DEFAULT 'PENDING',
    PRIMARY KEY (vote_id),
    UNIQUE KEY uk_client_id (client_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ─── Election event log (observability / experiment analysis) ───

CREATE TABLE IF NOT EXISTS election_log (
    id              INT            AUTO_INCREMENT PRIMARY KEY,
    event_type      VARCHAR(40)    NOT NULL,
    node_id         INT            NOT NULL,
    lamport_ts      BIGINT         NOT NULL,
    election_term   BIGINT         DEFAULT 0,
    initiator_id    INT            DEFAULT 0,
    details         JSON,
    logged_at_ms    BIGINT         NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ─── State Recovery / Sync Log (Phase 4 durability) ─────────────

CREATE TABLE IF NOT EXISTS sync_log (
    entry_id        INT            AUTO_INCREMENT PRIMARY KEY,
    entry_type      VARCHAR(40)    NOT NULL,
    vote_id         VARCHAR(128),
    client_id       VARCHAR(64),
    origin_node_id  INT,
    lamport_ts      BIGINT         NOT NULL,
    choice          VARCHAR(100),
    status          VARCHAR(16),
    details         TEXT,
    created_at_ms   BIGINT         NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
