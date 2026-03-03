"""Shared state and context for all workflows."""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class SharedContext:
    """Shared context across all agents and graphs."""

    # Deployment info
    deployment_name: str = ""
    deployment_version: str = ""
    environment: str = "staging"  # staging, production

    # System info
    docker_host: str = ""
    log_path: str = ""

    # Coordination
    request_id: str = ""
    user_initiator: str = ""

    # Metadata
    tags: dict[str, str] = field(default_factory=dict)
    custom_context: dict[str, Any] = field(default_factory=dict)
