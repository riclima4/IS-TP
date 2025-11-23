# Simple gRPC Greeter Server

This directory contains a minimal gRPC Greeter server.

Files added:

- `rpc.proto` - protobuf definition for Greeter service
- `rpc-server.py` - server script that generates Python stubs (if needed) and runs the server
- `requirements.txt` - dependencies

Quick start (Windows / bash):

```bash
python -m pip install -r requirements.txt
python rpc-server.py
```

Then the server will listen on port 50051. You can test with any gRPC client or create a small client using the generated `rpc_pb2.py` and `rpc_pb2_grpc.py` files after generation.
