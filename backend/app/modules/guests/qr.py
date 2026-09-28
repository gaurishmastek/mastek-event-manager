import secrets

import segno


def new_pass_token() -> str:
    """256 bits of randomness. The QR code carries only this token: no ids, names or event details."""
    return secrets.token_urlsafe(32)


def qr_svg_data_uri(token: str) -> str:
    return segno.make(token, error="m").svg_data_uri(scale=6, border=4)
