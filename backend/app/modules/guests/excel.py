"""Excel workbook generation for the admin registration export."""

from collections.abc import Iterable
from datetime import UTC, datetime, timedelta, timezone
from tempfile import SpooledTemporaryFile
from typing import BinaryIO

from openpyxl import Workbook
from openpyxl.cell import WriteOnlyCell
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter

from app.modules.guests.models import Registration

IST = timezone(timedelta(hours=5, minutes=30), name="IST")
DATETIME_FORMAT = "dd-mmm-yyyy hh:mm AM/PM"
FORMULA_PREFIXES = ("=", "+", "-", "@")

HEADERS = (
    "Registration ID",
    "Employee ID",
    "Employee Name",
    "Email (Masked)",
    "Mobile (Masked)",
    "Attending",
    "Family Attending",
    "Guest Names",
    "Adult Name",
    "Kid Names",
    "Kid Ages",
    "Food Preference",
    "Number of Guests",
    "Party Size",
    "Status",
    "Verified At (IST)",
    "QR Issued",
    "QR Issued At (IST)",
    "Checked In At (IST)",
    "Registered At (IST)",
    "People Entered",
)

COLUMN_WIDTHS = (38, 18, 24, 28, 20, 12, 18, 36, 24, 36, 16, 18, 18, 12, 18, 24, 12, 24, 24, 24, 14)


def _safe_text(value: str | None) -> str:
    """Prevent spreadsheet formula execution while retaining the displayed text."""
    if value is None:
        return ""
    if value.lstrip().startswith(FORMULA_PREFIXES):
        return f"'{value}"
    return value


def _yes_no(value: bool | None) -> str:
    if value is None:
        return ""
    return "Yes" if value else "No"


def _in_ist(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    aware = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    # Excel stores a wall-clock value without timezone information; the header declares IST.
    return aware.astimezone(IST).replace(tzinfo=None)


def _text_list(values: Iterable[object]) -> str:
    return _safe_text(", ".join(str(value) for value in values))


def _row(registration: Registration) -> tuple[object, ...]:
    return (
        _safe_text(registration.public_id),
        _safe_text(registration.employee_id),
        _safe_text(registration.employee_name),
        _safe_text(registration.email_masked),
        _safe_text(registration.mobile_masked),
        _yes_no(registration.attending),
        _yes_no(registration.family_attending),
        _text_list(registration.guest_names),
        _safe_text(registration.adult_name),
        _text_list(registration.kid_names),
        _text_list(age if age is not None else "" for age in registration.kid_ages),
        _safe_text(registration.food_preference),
        registration.number_of_guests,
        registration.party_size,
        _safe_text(registration.status),
        _in_ist(registration.verified_at),
        _yes_no(registration.qr_token_hash is not None),
        _in_ist(registration.qr_issued_at),
        _in_ist(registration.checked_in_at),
        _in_ist(registration.created_at),
        registration.people_entered,
    )


def build_registration_workbook(registrations: Iterable[Registration]) -> BinaryIO:
    """Create an XLSX in a spooled file so large events do not retain the full file in memory."""
    workbook = Workbook(write_only=True)
    workbook.properties.title = "Mastek event registrations"
    worksheet = workbook.create_sheet("Registrations")
    worksheet.freeze_panes = "A2"

    for index, width in enumerate(COLUMN_WIDTHS, start=1):
        worksheet.column_dimensions[get_column_letter(index)].width = width

    header_fill = PatternFill("solid", fgColor="1F4E78")
    header_font = Font(color="FFFFFF", bold=True)
    header_cells = []
    for heading in HEADERS:
        cell = WriteOnlyCell(worksheet, value=heading)
        cell.fill = header_fill
        cell.font = header_font
        header_cells.append(cell)
    worksheet.append(header_cells)

    row_count = 1
    date_columns = {16, 18, 19, 20}
    for registration in registrations:
        cells = []
        for column, value in enumerate(_row(registration), start=1):
            cell = WriteOnlyCell(worksheet, value=value)
            if column in date_columns and value is not None:
                cell.number_format = DATETIME_FORMAT
            cells.append(cell)
        worksheet.append(cells)
        row_count += 1

    worksheet.auto_filter.ref = f"A1:{get_column_letter(len(HEADERS))}{row_count}"
    output = SpooledTemporaryFile(max_size=2 * 1024 * 1024, mode="w+b")
    try:
        workbook.save(output)
        output.seek(0)
        return output
    except Exception:
        output.close()
        raise
