import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.crypto import decrypt_pii, encrypt_pii, keyed_hash, token_hash
from app.core.email import mask_email
from app.core.mobile import mask_mobile
from app.db.mixins import utcnow
from app.modules.events.models import Event
from app.modules.events.repository import EventRepository
from app.modules.guests.models import Registration, RegistrationStatus
from app.modules.guests.qr import new_pass_token, qr_svg_data_uri
from app.modules.guests.repository import RegistrationRepository
from app.modules.guests.schemas import RegistrationCreate, normalize_employee_id
from app.modules.otp.service import GUEST_VERIFY, OtpIssued, OtpService


class EventNotFoundError(Exception):
    pass


class RegistrationNotFoundError(Exception):
    pass


class RegistrationClosedError(Exception):
    pass


class EventFullError(Exception):
    """Not enough seats left for the whole party (employee plus guests)."""


class TooManyGuestsError(Exception):
    def __init__(self, limit: int) -> None:
        super().__init__(limit)
        self.limit = limit


class DuplicateRegistrationError(Exception):
    """The employee id or email is already used by a different registration for this event."""


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


@dataclass(frozen=True)
class DeclineRecorded:
    """Verification of an employee who said they will not attend: no seat is taken and no pass is issued."""

    registration: Registration
    event: Event


@dataclass(frozen=True)
class _Identity:
    employee_id: str
    employee_id_normalized: str
    email_hash: str


# Registrations the public form may still change: nothing is reserved or issued for them.
_EDITABLE_STATUSES = (RegistrationStatus.PENDING_OTP.value, RegistrationStatus.DECLINED.value)


def registration_closes_at(event: Event) -> datetime:
    return event.ends_at or event.starts_at


class GuestRegistrationService:
    """Public flow: an employee registers themselves and their accompanying guests from the event's
    registration link, verifies their email by OTP, and receives one QR pass for the whole party.

    A registration only takes seats once the email is verified, so unverified or fake sign-ups can
    never fill an event, and a party is admitted in full or not at all. An employee who answers that
    they will not attend verifies the same way, and is recorded as DECLINED without a seat or a pass.
    """

    def __init__(self, db: Session, otp: OtpService) -> None:
        self.db = db
        self.events = EventRepository(db)
        self.registrations = RegistrationRepository(db)
        self.otp = otp

    def event_info(self, event_public_id: str) -> tuple[Event, bool, int]:
        event = self._open_event(event_public_id, require_open=False)
        return event, utcnow() < registration_closes_at(event), self._seats_left(event)

    def register(self, event_public_id: str, data: RegistrationCreate, *, ip: str | None) -> OtpSentResult:
        event = self._open_event(event_public_id)
        guests = data.accompanying_guests
        if len(guests) > event.max_guests_per_registration:
            raise TooManyGuestsError(event.max_guests_per_registration)

        identity = _Identity(
            employee_id=data.employee_id,
            employee_id_normalized=normalize_employee_id(data.employee_id),
            email_hash=keyed_hash(data.email, purpose="email"),
        )
        registration = self._find_existing(event, identity)

        if registration is None:
            if data.attending:
                self._ensure_seats_available(event, 1 + len(guests))
            registration = Registration(
                public_id=str(uuid.uuid4()),
                event_id=event.id,
                status=RegistrationStatus.PENDING_OTP.value,
            )
            self._apply_form(registration, data, identity)
            try:
                self.registrations.add(registration)
            except IntegrityError:
                # The same employee or email registered for this event in a parallel request.
                self.db.rollback()
                registration = self._find_existing(event, identity)
                if registration is None:
                    raise
                if registration.status in _EDITABLE_STATUSES:
                    self._apply_form(registration, data, identity)
                    self.registrations.set_guests(registration, guests)
            else:
                self.registrations.set_guests(registration, guests)
        elif registration.status in _EDITABLE_STATUSES:
            # Nothing is reserved or issued yet, so the latest form submission wins, guests included. An
            # employee who declined can change their mind; they verify their email again either way.
            self._apply_form(registration, data, identity)
            self.registrations.set_guests(registration, guests)
        # A verified registration is never changed from the public form. Submitting the same employee
        # id and email again only sends a code, so a lost pass can be reissued after verification.

        return self._send_otp(event, registration, ip=ip)

    def resend_otp(self, public_id: str, *, ip: str | None) -> OtpSentResult:
        registration = self._get_registration(public_id)
        event = self._open_event_by_id(registration.event_id)
        return self._send_otp(event, registration, ip=ip)

    def verify(self, public_id: str, code: str) -> IssuedPass | DeclineRecorded:
        """Verify the OTP, reserve seats for the whole party, and issue a new pass. Verifying again
        later re-issues the pass and invalidates the old QR code (e.g. for an employee who lost it).

        For an employee who said they will not attend, record the decline instead: no seat, no pass."""
        registration = self._get_registration(public_id)
        self._open_event_by_id(registration.event_id)
        if registration.status == RegistrationStatus.CHECKED_IN.value:
            raise AlreadyCheckedInError

        self.otp.verify(purpose=GUEST_VERIFY, subject_ref=registration.public_id, code=code)

        now = utcnow()
        # Lock the event row so parallel verifications cannot take more seats than the capacity.
        event = self.events.get_for_update(registration.event_id)
        if event is None:
            self.db.rollback()
            raise EventNotFoundError
        # Locking reads from here on, so the status and seat count are the latest committed ones.
        self.db.refresh(registration, with_for_update=True)
        if registration.status == RegistrationStatus.CHECKED_IN.value:
            self.db.rollback()
            raise AlreadyCheckedInError
        if registration.status == RegistrationStatus.PENDING_OTP.value and not registration.attending:
            registration.status = RegistrationStatus.DECLINED.value
            registration.verified_at = now
        if registration.status == RegistrationStatus.DECLINED.value:
            self.db.commit()
            return DeclineRecorded(registration=registration, event=event)
        if registration.status == RegistrationStatus.PENDING_OTP.value:
            if registration.number_of_guests > event.max_guests_per_registration:
                # The admin lowered the limit after this form was submitted.
                self.db.rollback()
                raise TooManyGuestsError(event.max_guests_per_registration)
            if self.registrations.count_seats_taken(event.id, locking=True) + registration.party_size > event.capacity:
                self.db.rollback()
                raise EventFullError
            registration.status = RegistrationStatus.VERIFIED.value
            registration.verified_at = now

        token = new_pass_token()
        registration.qr_token_hash = token_hash(token)
        registration.qr_issued_at = now
        self.db.commit()
        return IssuedPass(registration=registration, event=event, token=token, qr_svg=qr_svg_data_uri(token))

    def _find_existing(self, event: Event, identity: _Identity) -> Registration | None:
        """The registration this submission belongs to, or None for a new one.

        Raises DuplicateRegistrationError when the employee id and the email point at different
        registrations, or when a verified registration is claimed with only one of the two.
        """
        by_email = self.registrations.get_by_event_and_email(event.id, identity.email_hash)
        by_employee = self.registrations.get_by_event_and_employee(event.id, identity.employee_id_normalized)
        if by_email is not None and by_employee is not None and by_email.id != by_employee.id:
            self.db.rollback()
            raise DuplicateRegistrationError
        registration = by_email or by_employee
        if (
            registration is not None
            and registration.status != RegistrationStatus.PENDING_OTP.value
            and (by_email is None or by_employee is None)
        ):
            # Changing the email or employee id of a verified registration is not allowed, and must not
            # send a code to (or reveal the masked address of) someone else's registration.
            self.db.rollback()
            raise DuplicateRegistrationError
        return registration

    @staticmethod
    def _apply_form(registration: Registration, data: RegistrationCreate, identity: _Identity) -> None:
        registration.employee_id = identity.employee_id
        registration.employee_id_normalized = identity.employee_id_normalized
        registration.employee_name = data.employee_name
        registration.email_hash = identity.email_hash
        registration.email_encrypted = encrypt_pii(data.email)
        registration.email_masked = mask_email(data.email)
        registration.mobile_hash = keyed_hash(data.mobile, purpose="mobile")
        registration.mobile_encrypted = encrypt_pii(data.mobile)
        registration.mobile_masked = mask_mobile(data.mobile)
        registration.attending = data.attending
        registration.family_attending = data.family_attending
        registration.food_preference = data.food_preference.value if data.food_preference is not None else None
        registration.consent_at = utcnow()
        # A declined registration being answered again goes back through email verification.
        registration.status = RegistrationStatus.PENDING_OTP.value
        registration.verified_at = None

    def _send_otp(self, event: Event, registration: Registration, *, ip: str | None) -> OtpSentResult:
        if registration.status == RegistrationStatus.CHECKED_IN.value:
            self.db.rollback()
            raise AlreadyCheckedInError
        if registration.status == RegistrationStatus.PENDING_OTP.value and registration.attending:
            # Don't spend an email on a party that could not get in anyway.
            self._ensure_seats_available(event, registration.party_size)
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

    def _open_event(self, event_public_id: str, *, require_open: bool = True) -> Event:
        return self._check_open(self.events.get_by_public_id(event_public_id), require_open=require_open)

    def _open_event_by_id(self, event_id: int) -> Event:
        return self._check_open(self.events.get(event_id), require_open=True)

    @staticmethod
    def _check_open(event: Event | None, *, require_open: bool) -> Event:
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

    def _seats_left(self, event: Event) -> int:
        return max(0, event.capacity - self.registrations.count_seats_taken(event.id))

    def _ensure_seats_available(self, event: Event, party_size: int) -> None:
        if self._seats_left(event) < party_size:
            self.db.rollback()
            raise EventFullError


class RegistrationListService:
    """Admin read access to an event's registrations. Callers must already be authorized as admin."""

    def __init__(self, db: Session) -> None:
        self.events = EventRepository(db)
        self.registrations = RegistrationRepository(db)

    def list(
        self, event_id: int, *, limit: int, offset: int, search: str | None, status: str | None
    ) -> tuple[list[Registration], int]:
        if self.events.get(event_id) is None:
            raise EventNotFoundError
        return self.registrations.list(event_id, limit=limit, offset=offset, search=search, status=status)
