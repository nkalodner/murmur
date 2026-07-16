"""Transcript cleanup before injection."""


def clean(text: str, trailing_space: bool = True) -> str:
    """Collapse whitespace; optionally add a trailing space so consecutive dictations flow."""
    out = " ".join(text.split())
    if not out:
        return ""
    return out + " " if trailing_space else out
