# Simple FastAPI REST API

This folder contains a minimal FastAPI application with an in-memory CRUD for `Item` resources.

Files:

- `app.py` - the FastAPI application
- `requirements.txt` - Python dependencies

Run locally (bash / Windows WSL):

```bash
python -m pip install -r requirements.txt
uvicorn app:app --reload --host 0.0.0.0 --port 8000
```

Open the interactive API docs at:

http://127.0.0.1:8000/docs

Example curl requests:

Create an item:

```bash
curl -sS -X POST http://127.0.0.1:8000/items \
  -H "Content-Type: application/json" \
  -d '{"name":"Widget","description":"A small widget","price":9.99}'
```

List items:

```bash
curl http://127.0.0.1:8000/items
```

Get item:

```bash
curl http://127.0.0.1:8000/items/1
```

Notes
- This is intentionally minimal and uses an in-memory store. For production, plug in a database and add validation, auth, and tests.
