#!/bin/bash
# Generate Python gRPC stubs from the PTSL proto file.
#
# Prerequisites:
#   pip3 install grpcio grpcio-tools
#
# Usage:
#   ./generate_proto.sh /path/to/PTSL_SDK_CPP/Source
#
# The PTSL SDK is available from Avid: https://my.avid.com
# You need your own licensed copy of the SDK.

if [ -z "$1" ]; then
    echo "Usage: ./generate_proto.sh /path/to/PTSL_SDK/Source"
    echo ""
    echo "Point this at the Source directory of your PTSL C++ SDK,"
    echo "which contains PTSL.proto."
    exit 1
fi

PROTO_DIR="$1"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

if [ ! -f "$PROTO_DIR/PTSL.proto" ]; then
    echo "Error: PTSL.proto not found in $PROTO_DIR"
    exit 1
fi

OUT_DIR="$SCRIPT_DIR/src/ptvc/proto"
mkdir -p "$OUT_DIR"

python3 -m grpc_tools.protoc \
    --proto_path="$PROTO_DIR" \
    --python_out="$OUT_DIR" \
    --grpc_python_out="$OUT_DIR" \
    "$PROTO_DIR/PTSL.proto"

# Fix the generated import to use a relative import within the package
sed -i '' 's/^import PTSL_pb2 as/from . import PTSL_pb2 as/' "$OUT_DIR/PTSL_pb2_grpc.py"

echo "Generated PTSL_pb2.py and PTSL_pb2_grpc.py in $OUT_DIR"
