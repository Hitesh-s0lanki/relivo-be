"""Compatibility route module for user files."""

from src.controllers.user_file_controller import (
    create_user_file_download_url,
    delete_user_file,
    get_user_file,
    get_user_file_service,
    list_user_files,
    router,
    upload_user_file,
)

__all__ = [
    "create_user_file_download_url",
    "delete_user_file",
    "get_user_file",
    "get_user_file_service",
    "list_user_files",
    "router",
    "upload_user_file",
]
