def normalize_email(email: str) -> str:
    """Trim and lower-case an address so hashes, lookups and uniqueness do not depend on how it was typed."""
    return email.strip().lower()


def mask_email(email: str) -> str:
    """asha.patil@example.com -> as•••@example.com"""
    local, _, domain = email.rpartition("@")
    return f"{local[:2]}•••@{domain}"
