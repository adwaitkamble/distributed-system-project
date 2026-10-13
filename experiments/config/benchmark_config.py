"""Configuration constants and defaults for the experiment and benchmark framework."""

from dataclasses import dataclass
from typing import Dict, List, Tuple


@dataclass(frozen=True)
class ClusterProfileConfig:
    node_count: int
    compose_file: str
    http_ports: Dict[int, int]
    grpc_ports: Dict[int, int]
    db_ports: Dict[int, int]


CLUSTER_PROFILES: Dict[int, ClusterProfileConfig] = {
    1: ClusterProfileConfig(
        node_count=1,
        compose_file="docker/docker-compose.single.yml",
        http_ports={1: 5000},
        grpc_ports={1: 50051},
        db_ports={1: 3306},
    ),
    3: ClusterProfileConfig(
        node_count=3,
        compose_file="docker/docker-compose.3node.yml",
        http_ports={1: 5001, 2: 5002, 3: 5003},
        grpc_ports={1: 55051, 2: 55052, 3: 55053},
        db_ports={1: 33061, 2: 33062, 3: 33063},
    ),
    5: ClusterProfileConfig(
        node_count=5,
        compose_file="docker/docker-compose.5node.yml",
        http_ports={1: 5001, 2: 5002, 3: 5003, 4: 5004, 5: 5005},
        grpc_ports={1: 55051, 2: 55052, 3: 55053, 4: 55054, 5: 55055},
        db_ports={1: 33061, 2: 33062, 3: 33063, 4: 33064, 5: 33065},
    ),
    7: ClusterProfileConfig(
        node_count=7,
        compose_file="docker/docker-compose.7node.yml",
        http_ports={1: 5001, 2: 5002, 3: 5003, 4: 5004, 5: 5005, 6: 5006, 7: 5007},
        grpc_ports={1: 55051, 2: 55052, 3: 55053, 4: 55054, 5: 55055, 6: 55056, 7: 55057},
        db_ports={1: 33061, 2: 33062, 3: 33063, 4: 33064, 5: 33065, 6: 33066, 7: 33067},
    ),
}

# Workload Defaults
DEFAULT_WARMUP_REQUESTS = 10
DEFAULT_BENCHMARK_REQUESTS = 100
DEFAULT_CONCURRENCY = 5
DEFAULT_REQUEST_TIMEOUT_SEC = 5.0
DEFAULT_SETTLEMENT_TIMEOUT_SEC = 15.0
DEFAULT_HEALTHCHECK_TIMEOUT_SEC = 30.0

DEFAULT_CANDIDATES: List[str] = ["Alice", "Bob", "Charlie"]

# Network and Container Names
NETWORK_NAME = "voting-net"
NODE_CONTAINER_PREFIX = "voting-node"
DB_CONTAINER_PREFIX = "voting-node"
DB_CONTAINER_SUFFIX = "-db"
