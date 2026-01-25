"""FastAPI application and routes."""

from .main import app
from .routes import router

__all__ = ["app", "router"]
