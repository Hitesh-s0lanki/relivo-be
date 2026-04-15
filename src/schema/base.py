"""Base Pydantic model with camelCase alias serialization."""

from pydantic import BaseModel, ConfigDict


class RelivoBaseModel(BaseModel):
    """Base model: accepts both snake_case and camelCase input; serializes to camelCase."""

    model_config = ConfigDict(populate_by_name=True, serialize_by_alias=True)
