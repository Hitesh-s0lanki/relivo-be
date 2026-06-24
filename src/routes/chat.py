"""Compatibility route module for chat."""

from src.agents import get_chat_agent
from src.controllers.chat_controller import chat, get_chat_service, router

__all__ = ["chat", "get_chat_agent", "get_chat_service", "router"]
