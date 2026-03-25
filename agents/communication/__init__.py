"""Communication agent module."""

from .agent import CommunicationAgent
from .email_service import EmailService
from .email_templates import (
    format_incident_report_html,
    format_incident_report_plain_text,
)

__all__ = [
    "CommunicationAgent",
    "EmailService",
    "format_incident_report_html",
    "format_incident_report_plain_text",
]
