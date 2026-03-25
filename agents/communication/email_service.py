"""Email service for sending incident reports."""

import asyncio
import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Any, Optional

from app.config import Config

logger = logging.getLogger(__name__)


class EmailService:
    """Service for sending emails via SMTP."""

    def __init__(
        self,
        smtp_server: str | None = None,
        smtp_port: int | None = None,
        sender_email: str | None = None,
        sender_password: str | None = None,
        use_tls: bool = True,
    ) -> None:
        """
        Initialize email service with SMTP configuration.
        
        Args:
            smtp_server: SMTP server address
            smtp_port: SMTP server port
            sender_email: Sender email address
            sender_password: SMTP password or API key
            use_tls: Whether to use TLS encryption
        """
        self.smtp_server = smtp_server or Config.SMTP_SERVER
        self.smtp_port = smtp_port or Config.SMTP_PORT
        self.sender_email = sender_email or Config.SENDER_EMAIL
        self.sender_password = sender_password or Config.SENDER_PASSWORD
        self.use_tls = use_tls
        self.enabled = (
            self.smtp_server
            and self.sender_email
            and self.sender_password
        )

    async def send_email(
        self,
        recipient_email: str,
        subject: str,
        html_body: str,
        plain_text_body: Optional[str] = None,
    ) -> dict[str, Any]:
        """
        Send an email asynchronously.
        
        Args:
            recipient_email: Recipient email address
            subject: Email subject
            html_body: HTML formatted email body
            plain_text_body: Plain text fallback (optional)
            
        Returns:
            Dictionary with status and details
        """
        if not self.enabled:
            logger.warning(
                "Email service not configured. Skipping email send to %s",
                recipient_email,
            )
            return {
                "status": "skipped",
                "reason": "Email service not configured",
                "recipient": recipient_email,
            }

        try:
            # Run SMTP operation in a thread pool to avoid blocking
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                self._send_smtp,
                recipient_email,
                subject,
                html_body,
                plain_text_body,
            )
            return result
        except Exception as e:
            logger.error(
                "Failed to send email to %s: %s",
                recipient_email,
                str(e),
                exc_info=True,
            )
            return {
                "status": "failed",
                "error": str(e),
                "recipient": recipient_email,
            }

    def _send_smtp(
        self,
        recipient_email: str,
        subject: str,
        html_body: str,
        plain_text_body: Optional[str] = None,
    ) -> dict[str, Any]:
        """
        Send email via SMTP (blocking operation).
        
        Args:
            recipient_email: Recipient email address
            subject: Email subject
            html_body: HTML formatted email body
            plain_text_body: Plain text fallback
            
        Returns:
            Dictionary with status and details
        """
        # Create message
        message = MIMEMultipart("alternative")
        message["Subject"] = subject
        message["From"] = self.sender_email
        message["To"] = recipient_email

        # Attach plain text and HTML parts
        if plain_text_body:
            text_part = MIMEText(plain_text_body, "plain")
            message.attach(text_part)

        html_part = MIMEText(html_body, "html")
        message.attach(html_part)

        # Send email
        try:
            with smtplib.SMTP(self.smtp_server, self.smtp_port, timeout=10) as server:
                if self.use_tls:
                    server.starttls()
                server.login(self.sender_email, self.sender_password)
                server.send_message(message)

            logger.info(
                "Email sent successfully to %s with subject: %s",
                recipient_email,
                subject,
            )
            return {
                "status": "success",
                "recipient": recipient_email,
                "subject": subject,
            }
        except smtplib.SMTPAuthenticationError as e:
            logger.error("SMTP authentication failed: %s", str(e))
            raise ValueError(f"SMTP authentication failed: {e}")
        except smtplib.SMTPException as e:
            logger.error("SMTP error: %s", str(e))
            raise RuntimeError(f"SMTP error: {e}")
        except Exception as e:
            logger.error("Unexpected error sending email: %s", str(e))
            raise
