"""Unit tests for NodeConfig validation and environment parsing.

Covers:
- missing or empty PEERS
- NODE_ID absent from PEERS
- duplicate peer IDs
- zero or negative heartbeat/election timing values
- invalid INITIAL_COORDINATOR_ID
"""

import pytest

from node.config import NodeConfig, PeerInfo


def _valid_config_kwargs():
    return {
        "node_id": 1,
        "grpc_port": 50051,
        "election_algorithm": "bully",
        "peers": {
            1: PeerInfo(1, "localhost", 50051),
            2: PeerInfo(2, "localhost", 50052),
        },
        "heartbeat_interval_ms": 1000,
        "heartbeat_timeout_ms": 3000,
        "election_timeout_ms": 5000,
        "replication_policy": "all",
        "initial_coordinator_id": 1,
        "db_host": "localhost",
        "db_port": 3306,
        "db_user": "root",
        "db_password": "votingpass",
        "db_name": "voting_node",
        "use_sqlite": True,
        "sqlite_path": ":memory:",
        "log_level": "INFO",
        "candidates": ["Alice", "Bob"],
    }


class TestNodeConfigValidation:
    """Direct validation tests on NodeConfig.validate()."""

    def test_valid_config_passes(self):
        cfg = NodeConfig(**_valid_config_kwargs())
        cfg.validate()  # Must not raise

    def test_empty_peers_raises(self):
        kwargs = _valid_config_kwargs()
        kwargs["peers"] = {}
        cfg = NodeConfig(**kwargs)
        with pytest.raises(ValueError, match="PEERS must contain at least one"):
            cfg.validate()

    def test_node_id_absent_from_peers_raises(self):
        kwargs = _valid_config_kwargs()
        kwargs["node_id"] = 3
        # peers only has 1 and 2
        cfg = NodeConfig(**kwargs)
        with pytest.raises(ValueError, match="NODE_ID=3 must be listed in PEERS"):
            cfg.validate()

    def test_peer_id_zero_or_negative_raises(self):
        kwargs = _valid_config_kwargs()
        kwargs["peers"] = {
            1: PeerInfo(1, "localhost", 50051),
            -2: PeerInfo(-2, "localhost", 50052),
        }
        cfg = NodeConfig(**kwargs)
        with pytest.raises(ValueError, match="Peer ID must be a positive integer"):
            cfg.validate()

    @pytest.mark.parametrize("param", [
        "heartbeat_interval_ms",
        "heartbeat_timeout_ms",
        "election_timeout_ms",
    ])
    @pytest.mark.parametrize("val", [0, -1, -500])
    def test_zero_or_negative_timing_values_raise(self, param, val):
        kwargs = _valid_config_kwargs()
        kwargs[param] = val
        cfg = NodeConfig(**kwargs)
        with pytest.raises(ValueError, match=f"{param.upper()} must be positive"):
            cfg.validate()

    def test_invalid_initial_coordinator_id_raises(self):
        kwargs = _valid_config_kwargs()
        kwargs["initial_coordinator_id"] = 99  # Not in {1, 2}
        cfg = NodeConfig(**kwargs)
        with pytest.raises(ValueError, match="not a configured cluster member"):
            cfg.validate()


class TestNodeConfigFromEnv:
    """Tests for environment variable parsing in NodeConfig.from_env()."""

    def test_missing_peers_env_raises(self, monkeypatch):
        monkeypatch.setenv("NODE_ID", "1")
        monkeypatch.delenv("PEERS", raising=False)
        with pytest.raises(ValueError, match="PEERS environment variable is required"):
            NodeConfig.from_env()

    def test_empty_peers_env_raises(self, monkeypatch):
        monkeypatch.setenv("NODE_ID", "1")
        monkeypatch.setenv("PEERS", "   ")
        with pytest.raises(ValueError, match="PEERS environment variable is required"):
            NodeConfig.from_env()

    def test_node_id_absent_from_peers_env_raises(self, monkeypatch):
        monkeypatch.setenv("NODE_ID", "1")
        monkeypatch.setenv("PEERS", "2:localhost:50052,3:localhost:50053")
        with pytest.raises(ValueError, match="NODE_ID=1 must be listed exactly once in PEERS"):
            NodeConfig.from_env()

    def test_duplicate_peer_ids_env_raises(self, monkeypatch):
        monkeypatch.setenv("NODE_ID", "1")
        monkeypatch.setenv("PEERS", "1:localhost:50051,1:localhost:50052")
        with pytest.raises(ValueError, match="Peer IDs in PEERS must be unique"):
            NodeConfig.from_env()

    def test_zero_timing_env_raises(self, monkeypatch):
        monkeypatch.setenv("NODE_ID", "1")
        monkeypatch.setenv("PEERS", "1:localhost:50051")
        monkeypatch.setenv("HEARTBEAT_INTERVAL_MS", "0")
        with pytest.raises(ValueError, match="HEARTBEAT_INTERVAL_MS must be positive"):
            NodeConfig.from_env()

    def test_invalid_initial_coordinator_env_raises(self, monkeypatch):
        monkeypatch.setenv("NODE_ID", "1")
        monkeypatch.setenv("PEERS", "1:localhost:50051")
        monkeypatch.setenv("INITIAL_COORDINATOR_ID", "42")
        with pytest.raises(ValueError, match="not a configured cluster member"):
            NodeConfig.from_env()

    def test_valid_env_succeeds(self, monkeypatch):
        monkeypatch.setenv("NODE_ID", "2")
        monkeypatch.setenv("PEERS", "1:localhost:50051,2:localhost:50052")
        monkeypatch.setenv("INITIAL_COORDINATOR_ID", "1")
        monkeypatch.setenv("USE_SQLITE", "true")
        cfg = NodeConfig.from_env()
        assert cfg.node_id == 2
        assert cfg.default_coordinator_id == 1
        assert cfg.peer_ids == [1]
