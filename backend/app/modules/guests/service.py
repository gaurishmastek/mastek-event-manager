import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.crypto import decrypt_pii, encrypt_pii, keyed_hash, token_hash
from app.core.email import mask_email
from app.db.mixins import utcnow
from app.modules.events.models import Event
from app.modules.events.repository import EventRepository
from app.modules.guests.models import Registration, RegistrationStatus
from app.modules.guests.qr import new_pass_token, qr_svg_data_uri
from app.modules.guests.repository import RegistrationRepository
from app.modules.guests.schemas import RegistrationCreate
from app.modules.otp.service import GUEST_VERIFY, OtpIssued, OtpService


class EventNotFoundError(Exception):
    pass


class RegistrationNotFoundError(Exception):
    pass


class RegistrationClosedError(Exception):
    pass


class EventFullError(Exception):
    pass


class AlreadyCheckedInError(Exception):
    pass


class NoEmailOnRegistrationError(Exception):
    """The registration predates email OTPs, so no code can be sent for it."""


@dataclass(frozen=True)
class OtpSentResult:
    registration: Registration
    otp: OtpIssued


@dataclass(frozen=True)
class IssuedPass:
    registration: Registration
    event: Event
    token: str
    qr_svg: str


def registration_closes_at(event: Event) -> datetime:
    return event.ends_at or event.starts_at


class GuestRegistrationService:
    """Public guest flow: register -> verify email by OTP -> receive a single-use QR pass.

    A registration only takes a seat once the email is verified, so unverified or fake
    sign-ups can never fill an event.
    """

    def __init__(self, db: Session, otp: OtpService) -> None:
        self.db = db
        self.events = EventRepository(db)
        self.registrations = RegistrationRepository(db)
        self.otp = otp

    def event_info(self, event_id: int) -> tuple[Event, bool, int]:
        event = self._open_event(event_id, require_open=False)
        seats_left = max(0, event.capacity - self.registrations.count_seats_taken(event.id))
        return event, utcnow() < registration_closes_at(event), seats_left

    def register(self, event_id: int, data: RegistrationCreate, *, ip: str | None) -> OtpSentResult:
        event = self._open_event(event_id)
        email_hash = keyed_hash(data.email, purpose="email")
        registration = self.registrations.get_by_event_and_email(event.id, email_hash)

        if registration is None:
            self._ensure_seat_available(event)
            now = utcnow()
            registration = Registration(
                public_id=str(uuid.uuid4()),
                event_id=event.id,
                guest_name=data.guest_name,
                email_hash=email_hash,
                email_encrypted=encrypt_pii(data.email),
                email_masked=mask_email(data.email),
                status=RegistrationStatus.PENDING_OTP.value,
                consent_at=now,
            )
            try:
                self.registrations.add(registration)
            except IntegrityError:
                # The same email registered for this event in a parallel request; continue with that one.
                self.db.rollback()
                registration = self.registrations.get_by_event_and_email(event.id, email_hash)
                if registration is None:
                    raise
        elif registration.status == RegistrationStatus.PENDING_OTP.value:
            # Nothing is verified yet, so the latest form submission wins.
            registration.guest_name = data.guest_name
            registration.consent_at = utcnow()

        return self._send_otp(event, registration, ip=ip)

    def resend_otp(self, public_id: str, *, ip: str | None) -> OtpSentResult:
        registration = self._get_registration(public_id)
        event = self._open_event(registration.event_id)
        return self._send_otp(event, registration, ip=ip)

    def verify(self, public_id: str, code: str) -> IssuedPass:
        """Verify the OTP and issue a new pass. Verifying again later re-issues the pass and
        invalidates the old QR code (e.g. for a guest who lost it)."""
        registration = self._get_registration(public_id)
        self._open_event(registration.event_id)
        if registration.status == RegistrationStatus.CHECKED_IN.value:
            raise AlreadyCheckedInError

        self.otp.verify(purpose=GUEST_VERIFY, subject_ref=registration.public_id, code=code)

        now = utcnow()
        # Lock the event row so parallel verifications cannot take more seats than the capacity.
        event = self.events.get_for_update(registration.event_id)
        if event is None:
            self.db.rollback()
            raise EventNotFoundError
        self.db.refresh(registration)
        if registration.status == RegistrationStatus.CHECKED_IN.value:
            self.db.rollback()
            raise AlreadyCheckedInError
        if registration.status == RegistrationStatus.PENDING_OTP.value:
            if self.registrations.count_seats_taken(event.id) >= event.capacity:
                self.db.rollback()
                raise EventFullError
            registration.status = RegistrationStatus.VERIFIED.value
            registration.verified_at = now

        token = new_pass_token()
        registration.qr_token_hash = token_hash(token)
        registration.qr_issued_at = now
        self.db.commit()
        return IssuedPass(registration=registration, event=event, token=token, qr_svg=qr_svg_data_uri(token))

    def _send_otp(self, event: Event, registration: Registration, *, ip: str | None) -> OtpSentResult:
        if registration.status == RegistrationStatus.CHECKED_IN.value:
            self.db.rollback()
            raise AlreadyCheckedInError
        if registration.status == RegistrationStatus.PENDING_OTP.value:
            # Don't spend an email on a guest who could not get a seat anyway.
            self._ensure_seat_available(event)
        if registration.email_encrypted is None:
            # Registered by mobile before the switch to email; there is nowhere to send a code.
            self.db.rollback()
            raise NoEmailOnRegistrationError
        try:
            issued = self.otp.issue(
                purpose=GUEST_VERIFY,
                subject_ref=registration.public_id,
                email=decrypt_pii(registration.email_encrypted),
                ip=ip,
            )
        except Exception:
            self.db.rollback()
            raise
        self.db.commit()
        return OtpSentResult(registration=registration, otp=issued)

    def _open_event(self, event_id: int, *, require_open: bool = True) -> Event:
        event = self.events.get(event_id)
        if event is None:
            raise EventNotFoundError
        if require_open and utcnow() >= registration_closes_at(event):
            raise RegistrationClosedError
        return event

    def _get_registration(self, public_id: str) -> Registration:
        registration = self.registrations.get_by_public_id(public_id)
        if registration is None:
            raise RegistrationNotFoundError
        return registration

    def _ensure_seat_available(self, event: Event) -> None:
        if self.registrations.count_seats_taken(event.id) >= event.capacity:
            self.db.rollback()
            raise EventFullError
