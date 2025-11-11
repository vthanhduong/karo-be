"""FastAPI application entrypoint for the caro backend."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.websocket import register_websocket_routes


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    application = FastAPI()
    application.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    register_websocket_routes(application)
    return application


app = create_app()

@app.get('/health-check')
async def health_check():
    """Health check endpoint"""
    return {"message": "Karo API Service is running."}