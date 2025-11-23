from typing import Optional, Dict

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI(title="Rest_api", version="0.1")

@app.get("/", tags=["root"])
def read_root():
    return {"message": "Hello from FastAPI REST API"}