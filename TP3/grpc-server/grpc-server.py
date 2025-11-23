import os
import subprocess
import sys
import time
from concurrent import futures

try:
    import grpc
except ImportError:
    print("grpc not installed. Run: python -m pip install -r requirements.txt")
    raise

HERE = os.path.dirname(os.path.abspath(__file__))
PROTO = os.path.join(HERE, "grpc.proto")
PB2 = os.path.join(HERE, "grpc_pb2.py")
PB2_GRPC = os.path.join(HERE, "grpc_pb2_grpc.py")


def _maybe_generate_protos():
    """Generate Python gRPC code from grpc.proto if generated files are missing."""
    if os.path.exists(PB2) and os.path.exists(PB2_GRPC):
        return

    print("Generating Python gRPC code from grpc.proto...")
    # Use grpc_tools.protoc to generate
    cmd = [
        sys.executable,
        "-m",
        "grpc_tools.protoc",
        f"-I{HERE}",
        f"--python_out={HERE}",
        f"--grpc_python_out={HERE}",
        PROTO,
    ]
    print("Running:", " ".join(cmd))
    subprocess.check_call(cmd)
    print("Generated rpc_pb2.py and rpc_pb2_grpc.py")


_maybe_generate_protos()

import grpc_pb2
import grpc_pb2_grpc


class GreeterServicer(grpc_pb2_grpc.GreeterServicer):
    """Provides methods that implement functionality of Greeter server."""

    def SayHello(self, request, context):
        name = request.name or "world"
        return rpc_pb2.HelloReply(message=f"Hello, {name}!")


def serve(host="0.0.0.0", port=50051):
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    grpc_pb2_grpc.add_GreeterServicer_to_server(GreeterServicer(), server)
    address = f"{host}:{port}"
    server.add_insecure_port(address)
    server.start()
    print(f"gRPC Greeter server started on {address}")
    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        print("Shutting down server...")
        server.stop(0)


if __name__ == "__main__":
    serve()
