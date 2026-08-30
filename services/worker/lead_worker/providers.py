from __future__ import annotations

import asyncio
import json
import smtplib
import uuid
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Protocol

import httpx
from lead_api.config import Settings


@dataclass(frozen=True)
class OutboundEmail:
    to_email: str
    subject: str
    text_body: str
    html_body: str | None = None


@dataclass(frozen=True)
class DeliveryResult:
    provider_message_id: str


class DeliveryError(Exception):
    def __init__(self, code: str, *, temporary: bool = True) -> None:
        super().__init__(code)
        self.code = code
        self.temporary = temporary


class EmailProvider(Protocol):
    name: str

    async def send(self, message: OutboundEmail) -> DeliveryResult:
        pass


class LocalSmtpProvider:
    name = "local-smtp"

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def send(self, message: OutboundEmail) -> DeliveryResult:
        return await asyncio.to_thread(self._send_sync, message)

    def _send_sync(self, message: OutboundEmail) -> DeliveryResult:
        email = EmailMessage()
        email["From"] = self._settings.email_from_address
        email["To"] = message.to_email
        email["Subject"] = message.subject
        email["Message-ID"] = f"<{uuid.uuid4()}@local.lead-intake>"
        email.set_content(message.text_body)
        if message.html_body is not None:
            email.add_alternative(message.html_body, subtype="html")

        try:
            with smtplib.SMTP(
                self._settings.email_smtp_host,
                self._settings.email_smtp_port,
                timeout=self._settings.email_smtp_timeout_seconds,
            ) as smtp:
                if self._settings.email_smtp_starttls:
                    smtp.starttls()
                if self._settings.email_smtp_username:
                    smtp.login(
                        self._settings.email_smtp_username,
                        self._settings.email_smtp_password,
                    )
                response = smtp.send_message(email)
        except (OSError, smtplib.SMTPException) as exc:
            raise DeliveryError(exc.__class__.__name__, temporary=True) from exc

        if response:
            raise DeliveryError("recipient_refused", temporary=True)
        return DeliveryResult(provider_message_id=email["Message-ID"] or "mailpit-accepted")


class ResendProvider:
    name = "resend"

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def send(self, message: OutboundEmail) -> DeliveryResult:
        if not self._settings.resend_api_key:
            raise DeliveryError("resend_api_key_missing", temporary=False)

        payload = {
            "from": self._settings.email_from_address,
            "to": [message.to_email],
            "subject": message.subject,
            "text": message.text_body,
        }
        if message.html_body is not None:
            payload["html"] = message.html_body

        try:
            async with httpx.AsyncClient(timeout=self._settings.resend_timeout_seconds) as client:
                response = await client.post(
                    self._settings.resend_api_url,
                    headers={
                        "Authorization": f"Bearer {self._settings.resend_api_key}",
                        "Content-Type": "application/json",
                    },
                    content=json.dumps(payload),
                )
        except httpx.HTTPError as exc:
            raise DeliveryError(exc.__class__.__name__, temporary=True) from exc

        if 200 <= response.status_code < 300:
            message_id = response.json().get("id")
            return DeliveryResult(provider_message_id=str(message_id or "resend-accepted"))
        if response.status_code in {408, 409, 425, 429} or response.status_code >= 500:
            raise DeliveryError(f"resend_http_{response.status_code}", temporary=True)
        raise DeliveryError(f"resend_http_{response.status_code}", temporary=False)


def provider_from_settings(settings: Settings) -> EmailProvider:
    if settings.email_provider == "resend":
        return ResendProvider(settings)
    return LocalSmtpProvider(settings)
