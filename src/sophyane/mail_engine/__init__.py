"""Sophyane native mail engine.

Phone-native protocol services:

    SMTP receive        127.0.0.1:2525
    SMTP submission     127.0.0.1:1587
    implicit TLS SMTP   127.0.0.1:1465
    IMAP                127.0.0.1:1993

These are local service ports. Public publication is a separate Sophyane
Edge concern.
"""

from .accounts import AccountStore
from .store import MailStore

__all__ = [
    "AccountStore",
    "MailStore",
]
