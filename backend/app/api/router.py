"""Aggregate API router. Mount new domains here as the project grows."""

from fastapi import APIRouter

from app.api.routes import books, health, passages, translation

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(books.router)
api_router.include_router(translation.router)
api_router.include_router(passages.router)
