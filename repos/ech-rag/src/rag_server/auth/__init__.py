"""
Authentication and authorization for RAG service using API key-based multi-tenancy.
"""

from .dependencies import api_key_header, get_current_project, get_project_id, require_api_key
from .models import ApiKeyValidationResult, ProjectAccess
from .security import SecurityAuditLogger, generate_api_key

__all__ = [
    "ProjectAccess",
    "ApiKeyValidationResult",
    "api_key_header",
    "get_current_project",
    "get_project_id",
    "require_api_key",
    "SecurityAuditLogger",
    "generate_api_key",
]
