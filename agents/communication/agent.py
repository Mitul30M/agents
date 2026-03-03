"""Communication agent for notifications."""

from typing import Any
import logging

from app import logger  # noqa: F401

logger = logging.getLogger(__name__)

class CommunicationAgent:
    """
    Sends notifications about incidents to external systems (Slack, email, etc.).
    """

    async def notify(self, incident: dict[str, Any]) -> None:
        logger.info(f"notifying incident {incident.get('id')} to stakeholders")
        # placeholder: integrate with webhook/SMTP in future
