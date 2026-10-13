"""Node entry point — wires config, DB, clock, state, election strategy, and gRPC server."""

import signal
import sys

from node.config import NodeConfig
from node.logging_config import setup_logging
from node.runtime import NodeRuntime


def serve() -> None:
    """Start the node gRPC server and block until interrupted."""
    config = NodeConfig.from_env()
    logger = setup_logging(config.node_id, config.log_level)

    logger.info("Starting node %d with algorithm %s", config.node_id, config.election_algorithm)
    runtime = NodeRuntime(config=config, logger=logger)
    runtime.start()

    import os
    if os.environ.get("ENABLE_WEB_BRIDGE", "").lower() in ("true", "1", "yes"):
        from api.server import start_bridge_thread
        web_port = int(os.environ.get("HTTP_PORT") or os.environ.get("WEB_PORT", "5000"))
        web_host = os.environ.get("HOST") or os.environ.get("WEB_HOST", "0.0.0.0")
        start_bridge_thread(runtime, host=web_host, port=web_port)

    def _shutdown(signum, frame):
        logger.info("Received signal %s, shutting down...", signum)
        runtime.stop(grace=2.0)
        sys.exit(0)

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    runtime.server.wait_for_termination()


if __name__ == "__main__":
    serve()
