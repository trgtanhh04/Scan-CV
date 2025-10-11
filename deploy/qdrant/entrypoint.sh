#!/bin/sh
set -e

# Cloud Run passes PORT env, default to 8080 if not set
QDRANT_HTTP_PORT=${PORT:-8080}

# GRPC port (optional)
: ${QDRANT__SERVICE__GRPC_PORT:=6334}

# Export environment variables for Qdrant
export QDRANT__SERVICE__HTTP_PORT=${QDRANT_HTTP_PORT}
export QDRANT__SERVICE__GRPC_PORT=${QDRANT__SERVICE__GRPC_PORT}
export QDRANT__SERVICE__ENABLE_HTTP2=true
export QDRANT__LOG_LEVEL=${QDRANT__LOG_LEVEL:-INFO}

echo "Starting Qdrant on HTTP port $QDRANT_HTTP_PORT"

# Run the binary from a known path
exec /usr/local/bin/qdrant "$@"
