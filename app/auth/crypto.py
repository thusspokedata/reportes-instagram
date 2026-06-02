"""Symmetric encryption of access tokens at rest.

Tokens belong to third parties and must never be stored in clear text. We use
Fernet (authenticated symmetric encryption from the ``cryptography`` library)
with a dedicated key read from ``TOKEN_ENCRYPTION_KEY`` in the environment.
"""

from cryptography.fernet import Fernet
from flask import current_app


def _fernet():
    key = current_app.config["TOKEN_ENCRYPTION_KEY"]
    if isinstance(key, str):
        key = key.encode()
    return Fernet(key)


def encrypt_token(token: str) -> str:
    """Encrypt a token, returning text safe to store in a TEXT column."""
    return _fernet().encrypt(token.encode()).decode()


def decrypt_token(ciphertext: str) -> str:
    """Decrypt a token previously produced by :func:`encrypt_token`."""
    if isinstance(ciphertext, str):
        ciphertext = ciphertext.encode()
    return _fernet().decrypt(ciphertext).decode()
