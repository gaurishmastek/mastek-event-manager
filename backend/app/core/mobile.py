import re

# Indian mobile numbers only: optional +91 / 91 / 0 prefix, then 10 digits starting 6-9.
# Restricting to Indian numbers also blocks most premium-rate SMS pumping.
_INDIAN_MOBILE = re.compile(r"^(?:\+91|91|0)?([6-9]\d{9})$")
_SEPARATORS = re.compile(r"[\s\-()]")


def normalize_indian_mobile(value: str) -> str:
    """Return the number as +91XXXXXXXXXX, or raise ValueError."""
    match = _INDIAN_MOBILE.fullmatch(_SEPARATORS.sub("", value))
    if match is None:
        raise ValueError("must be a valid Indian mobile number, e.g. 98765 43210")
    return f"+91{match.group(1)}"


def mask_mobile(e164: str) -> str:
    """+919876543210 -> 98•••••210"""
    digits = e164[-10:]
    return f"{digits[:2]}{'•' * 5}{digits[-3:]}"
