"""Flask REST bridge server runner."""

import os
import signal
import sys
import threading
import logging
from api import create_app
from node.config import NodeConfig
from node.logging_config import setup_logging
from node.runtime import NodeRuntime

logger = logging.getLogger("api.server")


def start_bridge_thread(runtime: NodeRuntime, host: str = "0.0.0.0", port: int = 5000) -> threading.Thread:
    """Start Flask REST bridge in a background daemon thread."""
    app = create_app(runtime=runtime)

    def _run():
        logger.info("Starting Flask REST bridge on http://%s:%d", host, port)
        # Suppress development server banner in logs
        from werkzeug.serving import make_server
        server = make_server(host, port, app, threaded=True)
        server.serve_forever()

    t = threading.Thread(target=_run, daemon=True, name="FlaskBridgeThread")
    t.start()
    return t


def serve_standalone():
    """Start NodeRuntime and Flask REST bridge server as a combined standalone process."""
    config = NodeConfig.from_env()
    log = setup_logging(config.node_id, config.log_level)
    log.info("Starting NodeRuntime and Flask Bridge for Node %d", config.node_id)

    runtime = NodeRuntime(config=config, logger=log)
    runtime.start()

    port = int(os.environ.get("WEB_PORT", "5000"))
    host = os.environ.get("WEB_HOST", "0.0.0.0")

    app = create_app(runtime=runtime)

    def _shutdown(signum, frame):
        log.info("Received shutdown signal %s", signum)
        runtime.stop(grace=1.0)
        sys.exit(0)

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    log.info("Serving REST API and React UI on http://%s:%d", host, port)
    app.run(host=host, port=port, threaded=True)


if __name__ == "__main__":
    serve_standalone()
