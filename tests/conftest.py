"""Shared pytest fixtures for the Distributed Voting System tests.

Amendment 5: each node uses an isolated temporary SQLite FILE, not
a shared in-memory database.

Amendment 7: proto stubs are regenerated before the test session.
"""

import os
import socket
import subprocess
import sys
import time
from concurrent import futures

import pytest

# ── Amendment 7: regenerate proto stubs before any imports that need them ──

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def pytest_configure(config):
    """Session-wide hook: ensure proto stubs are up-to-date."""
    gen_script = os.path.join(PROJECT_ROOT, "generate_proto.py")
    if os.path.exists(gen_script):
        result = subprocess.run(
            [sys.executable, gen_script],
            capture_output=True, text=True,
            cwd=PROJECT_ROOT,
        )
        if result.returncode != 0:
            raise RuntimeError(f"Proto generation failed:\n{result.stderr}")

    # Register custom markers
    config.addinivalue_line("markers", "mysql: tests that require a live MySQL instance")


# ── Fixtures ─────────────────────────────────────────────────────

@pytest.fixture
def lamport_clock():
    from node.lamport import LamportClock
    return LamportClock()


@pytest.fixture
def tmp_db_path(tmp_path):
    """Amendment 5: isolated temporary SQLite file for one test node."""
    return str(tmp_path / "test_node.db")


@pytest.fixture
def db_manager(tmp_db_path):
    """DatabaseManager backed by an isolated SQLite file."""
    from node.db import DatabaseManager
    db = DatabaseManager(use_sqlite=True, sqlite_path=tmp_db_path)
    db.initialize()
    yield db
    db.close()


@pytest.fixture
def node_config():
    """Minimal config for single-node / unit tests."""
    from node.config import NodeConfig
    return NodeConfig(
        node_id=1,
        grpc_port=0,  # will be overridden by grpc fixtures
        election_algorithm="bully",
        peers={1: _peer_info(1, "localhost", 50051)},
        heartbeat_interval_ms=1000,
        heartbeat_timeout_ms=3000,
        election_timeout_ms=5000,
        replication_policy="all",
        initial_coordinator_id=1,   # amendment 1: self is initial coordinator
        db_host="localhost",
        db_port=3306,
        db_user="root",
        db_password="votingpass",
        db_name="voting_node",
        use_sqlite=True,
        sqlite_path=None,  # set per-fixture
        log_level="DEBUG",
        candidates=["Alice", "Bob", "Charlie"],
    )


@pytest.fixture
def follower_config():
    """Config where this node is NOT the coordinator."""
    from node.config import NodeConfig
    return NodeConfig(
        node_id=1,
        grpc_port=0,
        election_algorithm="bully",
        peers={
            1: _peer_info(1, "localhost", 50051),
            2: _peer_info(2, "localhost", 50052),
        },
        heartbeat_interval_ms=1000,
        heartbeat_timeout_ms=3000,
        election_timeout_ms=5000,
        replication_policy="all",
        initial_coordinator_id=None,  # amendment 1: highest = 2, so node 1 is follower
        db_host="localhost",
        db_port=3306,
        db_user="root",
        db_password="votingpass",
        db_name="voting_node",
        use_sqlite=True,
        sqlite_path=None,
        log_level="DEBUG",
        candidates=["Alice", "Bob", "Charlie"],
    )


@pytest.fixture
def grpc_server_and_stub(tmp_path, node_config):
    """Start a real in-process gRPC server and return a client stub.

    Yields (stub, server, db, clock, state) so tests can inspect internal state.
    """
    import grpc
    from node.coordinator import CoordinatorState
    from node.db import DatabaseManager
    from node.lamport import LamportClock
    from node.service_impl import VotingServicer
    from node.vote_service import VoteService
    from node.generated import voting_pb2_grpc

    db_path = str(tmp_path / "grpc_test_node.db")
    node_config.sqlite_path = db_path

    clock = LamportClock()
    db = DatabaseManager(use_sqlite=True, sqlite_path=db_path)
    db.initialize()
    state = CoordinatorState(node_config.node_id, node_config.default_coordinator_id)
    vote_svc = VoteService(db, clock, state, node_config)
    servicer = VotingServicer(vote_svc, db, clock, state, node_config)

    server = grpc.server(futures.ThreadPoolExecutor(max_workers=4))
    voting_pb2_grpc.add_NodeServiceServicer_to_server(servicer, server)
    port = _find_free_port()
    server.add_insecure_port(f"localhost:{port}")
    server.start()

    channel = grpc.insecure_channel(f"localhost:{port}")
    stub = voting_pb2_grpc.NodeServiceStub(channel)

    yield stub, server, db, clock, state

    channel.close()
    server.stop(grace=1)
    db.close()


# ── Helpers ──────────────────────────────────────────────────────

def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


def _peer_info(node_id: int, host: str, port: int):
    from node.config import PeerInfo
    return PeerInfo(node_id=node_id, host=host, port=port)
