"""Communication agent for incident notifications via email."""

import asyncio
import json
import logging
from typing import Any, Optional

import redis

from app import logger  # noqa: F401
from app.config import Config
from .email_service import EmailService
from .email_templates import (
    format_incident_report_html,
    format_incident_report_plain_text,
)

logger = logging.getLogger(__name__)


class CommunicationAgent:
    """
    Sends notifications about incidents to developers via email.

    Takes the incident state with diagnosis and remediation results,
    formats a professional email report, and sends it to the developer's email.
    """

    def __init__(
        self,
        email_service: Optional[EmailService] = None,
        redis_url: str | None = None,
        remediation_stream: str | None = None,
    ) -> None:
        """
        Initialize communication agent.

        Args:
            email_service: Optional custom EmailService instance
        """
        self.email_service = email_service or EmailService()
        self._redis = redis.from_url(redis_url or Config.REDIS_URL)
        self._remediation_stream = remediation_stream or Config.REMEDIATION_STREAM
        self._last_id: str = "0-0"

    async def notify(self, incident_data: dict[str, Any]) -> dict[str, Any]:
        """
        Send incident notification to developers via email.

        Args:
            incident_data: Dict containing:
                - incident_id: Unique incident identifier
                - created_at: ISO8601 timestamp
                - error_message: Error message from logs
                - error_location: Where error occurred (file/function)
                - diagnosis: Dict with diagnosis results (root_cause, confidence, patterns_detected, explanation, recommended_action)
                - remediation: Dict with remediation results (fix_type, decision, github_actions)
                - developer_email: Email to send report to (defaults to Config.DEVELOPER_EMAIL)

        Returns:
            Dict with notification status
        """
        try:
            incident_id = incident_data.get("incident_id", "unknown")
            logger.info(f"Preparing incident report for {incident_id}")

            # Extract data
            timestamp = incident_data.get("created_at", "Unknown")
            error_message = incident_data.get("error_message", "Unknown error")
            error_location = incident_data.get("error_location", "Unknown location")
            diagnosis = incident_data.get("diagnosis", {})
            remediation = incident_data.get("remediation", {})
            developer_email = (
                incident_data.get("developer_email") or Config.DEVELOPER_EMAIL
            )

            if not developer_email:
                logger.warning(
                    "No developer email configured for incident %s. "
                    "Set DEVELOPER_EMAIL env variable to enable notifications.",
                    incident_id,
                )
                return {
                    "status": "skipped",
                    "reason": "No developer email configured",
                    "incident_id": incident_id,
                }

            # Generate email subject
            root_cause = diagnosis.get("root_cause", "Unknown Issue")
            subject = f"[Incident Report] {root_cause} - {incident_id}"

            # Format email body (HTML and plain text)
            html_body = format_incident_report_html(
                incident_id=incident_id,
                timestamp=timestamp,
                error_message=error_message,
                error_location=error_location,
                diagnosis=diagnosis,
                remediation=remediation,
            )

            plain_text_body = format_incident_report_plain_text(
                incident_id=incident_id,
                timestamp=timestamp,
                error_message=error_message,
                error_location=error_location,
                diagnosis=diagnosis,
                remediation=remediation,
            )

            # Send email
            logger.info(f"Sending incident report to {developer_email}")
            result = await self.email_service.send_email(
                recipient_email=developer_email,
                subject=subject,
                html_body=html_body,
                plain_text_body=plain_text_body,
            )

            logger.info(
                f"Incident notification sent for {incident_id}: {result.get('status')}"
            )
            return {
                **result,
                "incident_id": incident_id,
            }

        except Exception as e:
            logger.error(
                f"Failed to notify incident {incident_data.get('incident_id')}: {str(e)}",
                exc_info=True,
            )
            return {
                "status": "failed",
                "error": str(e),
                "incident_id": incident_data.get("incident_id", "unknown"),
            }

    async def run_forever(self, poll_interval: float = 2.0) -> None:
        """Continuously consume remediation results and send notifications."""
        logger.info(
            "Starting CommunicationAgent loop (remediation_stream=%s)",
            self._remediation_stream,
        )

        try:
            while True:
                try:
                    handled = await self._process_new_remediations()
                    if handled == 0:
                        await asyncio.sleep(poll_interval)
                except Exception as exc:
                    logger.exception("Error in communication loop: %s", exc)
                    await asyncio.sleep(poll_interval)
        except asyncio.CancelledError:  # pragma: no cover - normal shutdown
            logger.info("CommunicationAgent loop cancelled; shutting down")

    async def _process_new_remediations(
        self, count: int = 10, block_ms: int = 1000
    ) -> int:
        """Read and process new remediation entries from Redis stream."""

        def _read():
            try:
                streams = {self._remediation_stream: self._last_id}
                return self._redis.xread(streams, count=count, block=block_ms)
            except Exception as exc:  # pragma: no cover - defensive
                logger.exception(
                    "Failed to read from remediation stream %s: %s",
                    self._remediation_stream,
                    exc,
                )
                return []

        data = await asyncio.to_thread(_read)
        if not data:
            return 0

        handled = 0
        for _stream, messages in data:
            for entry_id, fields in messages:
                decoded_id = (
                    entry_id.decode() if isinstance(entry_id, bytes) else str(entry_id)
                )
                self._last_id = decoded_id

                try:
                    payload = self._decode_fields(fields)
                    incident_data = self._build_incident_data(payload)
                    result = await self.notify(incident_data)

                    status = result.get("status")
                    if status in {"success", "skipped"}:
                        deleted = await asyncio.to_thread(
                            self._redis.xdel, self._remediation_stream, decoded_id
                        )
                        logger.info(
                            "Deleted %d remediation entry from %s after communication: %s",
                            int(deleted),
                            self._remediation_stream,
                            decoded_id,
                        )
                        handled += 1
                    else:
                        logger.warning(
                            "Communication failed for remediation entry %s; retained in stream",
                            decoded_id,
                        )
                except Exception as exc:  # pragma: no cover - defensive
                    logger.exception(
                        "Failed to process remediation entry %s: %s",
                        decoded_id,
                        exc,
                    )

        return handled

    @staticmethod
    def _decode_fields(fields: dict[bytes, bytes]) -> dict[str, Any]:
        """Decode Redis stream fields into a Python dictionary."""
        decoded = {k.decode(): v.decode() for k, v in fields.items()}
        if "data" in decoded:
            try:
                return json.loads(decoded["data"])
            except Exception:
                logger.warning(
                    "Failed to parse remediation JSON payload; using raw fields"
                )
        return decoded

    @staticmethod
    def _build_incident_data(remediation_payload: dict[str, Any]) -> dict[str, Any]:
        """Map remediation payload into communication input format."""
        return {
            "incident_id": remediation_payload.get("incident_id", "unknown-incident"),
            # Current remediation payload does not guarantee exact error timestamp/location.
            "created_at": remediation_payload.get("created_at")
            or remediation_payload.get("timestamp")
            or "Unknown",
            "error_message": remediation_payload.get("error_message")
            or remediation_payload.get("error_logs")
            or remediation_payload.get("explanation")
            or "Unknown error",
            "error_location": remediation_payload.get("error_location")
            or remediation_payload.get("service")
            or "Unknown location",
            "diagnosis": {
                "root_cause": remediation_payload.get("root_cause", "Unknown"),
                "confidence": remediation_payload.get("confidence", 0.0),
                "patterns_detected": remediation_payload.get("patterns_detected", []),
                "explanation": remediation_payload.get("explanation", ""),
                "recommended_action": remediation_payload.get("recommended_action", ""),
            },
            "remediation": remediation_payload,
        }
