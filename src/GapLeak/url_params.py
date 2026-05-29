"""URL parameter obfuscation for experiment conditions.

Keeps experiment modes out of agent-visible URLs so that models cannot
detect attack/defence conditions from the query string.  Internal code
continues to use descriptive names; only the wire format changes.

Encoding (internal -> URL):
    portal mode:  benign -> "a",  covert/covert-attack -> "b",  explicit -> "c"
    support mode: none -> "0",  summary -> "1",  full-summary -> "2",
                  soft -> "3",  restriction -> "4"

Parameter names:
    mode -> "v",  support -> "d",
    origin_mode -> "ov",  origin_support -> "od"
"""

from __future__ import annotations

# --- Parameter name mapping ---

PARAM_NAME: dict[str, str] = {
    "mode": "v",
    "support": "d",
    "origin_mode": "ov",
    "origin_support": "od",
}

# --- Value encoding (internal -> URL) ---

_PORTAL_TO_URL: dict[str, str] = {
    "benign": "a",
    "covert-attack": "b",
    "covert": "b",
    "explicit": "c",
}

_SUPPORT_TO_URL: dict[str, str] = {
    "none": "0",
    "summary": "1",
    "full-summary": "2",
    "soft": "3",
    "restriction": "4",
}

# --- Value decoding (URL -> internal) ---

_URL_TO_PORTAL: dict[str, str] = {
    "a": "benign",
    "b": "covert",
    "c": "explicit",
}

_URL_TO_SUPPORT: dict[str, str] = {
    "0": "none",
    "1": "summary",
    "2": "full-summary",
    "3": "soft",
    "4": "restriction",
}


def enc_portal(value: str) -> str:
    return _PORTAL_TO_URL.get(value, value)


def enc_support(value: str) -> str:
    return _SUPPORT_TO_URL.get(value, value)


def dec_portal(value: str) -> str:
    return _URL_TO_PORTAL.get(value, value)


def dec_support(value: str) -> str:
    return _URL_TO_SUPPORT.get(value, value)
