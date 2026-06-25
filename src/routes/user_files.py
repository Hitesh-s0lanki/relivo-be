"""Compatibility route module for user files."""

from src.controllers.user_file_controller import (
    ai_router,
    create_ai_attachment_presigned_url,
    create_user_file_download_url,
    delete_user_file,
    get_upload_conversation_service,
    get_user_file,
    get_user_file_service,
    list_user_files,
    router,
    upload_ai_attachments,
    upload_user_file,
)

__all__ = [
    "ai_router",
    "create_ai_attachment_presigned_url",
    "create_user_file_download_url",
    "delete_user_file",
    "get_user_file",
    "get_upload_conversation_service",
    "get_user_file_service",
    "list_user_files",
    "router",
    "upload_ai_attachments",
    "upload_user_file",
]
