"""Standalone FastAPI app for developing/demoing the LLM pipeline on its own.

Run:  uvicorn llm_pipeline.server:app --reload --port 8001
Docs: http://localhost:8001/docs

The real backend should mount ``llm_pipeline.api.router`` instead of using this.
"""

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api import router

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

app = FastAPI(title="Requirements-to-Test LLM Pipeline", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router)
