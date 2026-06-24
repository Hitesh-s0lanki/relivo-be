"""Compatibility route module for health checks."""

from src.controllers.health_controller import HealthResponse, health, router

__all__ = ["HealthResponse", "health", "router"]
