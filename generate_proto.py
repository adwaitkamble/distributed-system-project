#!/usr/bin/env python3
"""Generate gRPC Python stubs from voting.proto.

Run from the project root:
    python generate_proto.py

Generated files land in node/generated/ and are importable as:
    from node.generated import voting_pb2, voting_pb2_grpc

This script is also called by conftest.py (tests) and Dockerfile (builds)
to ensure stubs are always in sync with voting.proto  (amendment 7).
"""

import os
import subprocess
import sys

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
PROTO_DIR = os.path.join(PROJECT_ROOT, "proto")
OUT_DIR = os.path.join(PROJECT_ROOT, "node", "generated")
PROTO_FILE = os.path.join(PROTO_DIR, "voting.proto")


def generate() -> None:
    os.makedirs(OUT_DIR, exist_ok=True)

    # Ensure __init__.py so the directory is a proper package
    init_path = os.path.join(OUT_DIR, "__init__.py")
    if not os.path.exists(init_path):
        with open(init_path, "w") as f:
            f.write("# Auto-generated gRPC stubs — do not edit by hand.\n")

    cmd = [
        sys.executable,
        "-m",
        "grpc_tools.protoc",
        f"-I{PROTO_DIR}",
        f"--python_out={OUT_DIR}",
        f"--pyi_out={OUT_DIR}",
        f"--grpc_python_out={OUT_DIR}",
        PROTO_FILE,
    ]

    print(f"[generate_proto] Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"[generate_proto] FAILED:\n{result.stderr}", file=sys.stderr)
        sys.exit(1)

    # ------------------------------------------------------------------
    # Fix imports: the generated *_grpc.py uses a bare
    #   import voting_pb2 as voting__pb2
    # which breaks when the file lives inside node/generated/.
    # Replace with a relative import.
    # ------------------------------------------------------------------
    grpc_file = os.path.join(OUT_DIR, "voting_pb2_grpc.py")
    if os.path.exists(grpc_file):
        with open(grpc_file, "r", encoding="utf-8") as f:
            content = f.read()
        fixed = content.replace(
            "import voting_pb2 as voting__pb2",
            "from . import voting_pb2 as voting__pb2",
        )
        if fixed != content:
            with open(grpc_file, "w", encoding="utf-8") as f:
                f.write(fixed)
            print("[generate_proto] Fixed relative import in voting_pb2_grpc.py")

    print("[generate_proto] Done.")


if __name__ == "__main__":
    generate()
