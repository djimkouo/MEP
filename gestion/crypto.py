"""Chiffrement des données sensibles stockées en base (numéro de pièce d'identité)."""
from cryptography.fernet import Fernet
from sqlalchemy.types import Text, TypeDecorator

_fernet = None


def init_app(app):
    global _fernet
    _fernet = Fernet(app.config["FERNET_KEY"])


class EncryptedString(TypeDecorator):
    """Colonne texte chiffrée de façon transparente (Fernet / AES-128 + HMAC)."""

    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None or value == "":
            return None
        return _fernet.encrypt(value.encode("utf-8")).decode("ascii")

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return _fernet.decrypt(value.encode("ascii")).decode("utf-8")
