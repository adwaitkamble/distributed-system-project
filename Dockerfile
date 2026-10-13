# ==============================================================================
# Multi-Stage Dockerfile for Distributed Fault-Tolerant Voting System Node
# ==============================================================================

# ── Stage 1: Build React Production Frontend ──────────────────────────────────
FROM node:20-alpine AS frontend-builder
WORKDIR /build

COPY frontend/package*.json ./
RUN npm ci

COPY frontend/ ./
RUN npm run build

# ── Stage 2: Python 3.11 Runtime ──────────────────────────────────────────────
FROM python:3.11-slim
WORKDIR /app

# Install curl for container health check
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy protobuf definition and build gRPC stubs
COPY proto/ proto/
COPY generate_proto.py .
RUN python generate_proto.py

# Copy application backend services and REST bridge
COPY node/ node/
COPY api/ api/

# Copy compiled React frontend assets from Stage 1
COPY --from=frontend-builder /build/dist frontend/dist

# Expose gRPC port (50051) and REST/Web port (5000)
EXPOSE 50051 5000

# Default environment configuration
ENV PYTHONUNBUFFERED=1 \
    ENABLE_WEB_BRIDGE=true \
    HTTP_PORT=5000 \
    GRPC_PORT=50051 \
    USE_SQLITE=false

# Container healthcheck against Flask health endpoint
HEALTHCHECK --interval=5s --timeout=3s --retries=10 --start-period=5s \
    CMD curl -f http://localhost:5000/api/health || exit 1

# Start the node runtime (which starts gRPC + Flask REST bridge)
CMD ["python", "-m", "node.main"]
