"""Source resource discovery and processed resource references."""

from ksm2sdvx.resources.discovery import discover_resources
from ksm2sdvx.resources.models import (
    ProcessedResource,
    ResourceInput,
    ResourceInventory,
    ResourceRecord,
    ResourceReference,
    ResourceUse,
)

__all__ = [
    "ProcessedResource",
    "ResourceInput",
    "ResourceInventory",
    "ResourceRecord",
    "ResourceReference",
    "ResourceUse",
    "discover_resources",
]
