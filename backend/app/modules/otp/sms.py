"""SMS delivery for OTPs.

Only adapters with no real provider exist so far. A real provider (DLT-registered sender and
template) plugs in by implementing `SmsSender` and returning it from `get_sms_sender`.
"""

import sys
from typing import Protocol

from app.core.config import settings
from app.core.mobile import mask_mobile


class SmsDeliveryError(Exception):
    pass


class SmsSender(Protocol):
    def send_otp(self, mobile: str, code: str) -> None: ...


class DisabledSmsSender:
    def send_otp(self, mobile: str, code: str) -> None:
        raise SmsDeliveryError("SMS delivery is not configured")


class ConsoleSmsSender:
    """Development only: prints the OTP to stdout instead of sending it. Refused in production by config."""

    def send_otp(self, mobile: str, code: str) -> None:
        print(f"[dev sms] OTP for {mask_mobile(mobile)}: {code}", file=sys.stdout, flush=True)


def get_sms_sender() -> SmsSender:
    if settings.sms_provider == "console" and settings.environment != "production":
        return ConsoleSmsSender()
    return DisabledSmsSender()
