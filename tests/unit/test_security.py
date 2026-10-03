"""Unit-тесты для app.core.security."""

from datetime import timedelta
from unittest.mock import patch

import pytest
from jose import JWTError

from app.core.security import (
    _create_token,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)


# ===========================================================================
# Пароли
# ===========================================================================

class TestPasswordHashing:
    def test_hash_returns_different_string(self) -> None:
        h = hash_password("secret123")
        assert h != "secret123"
        assert len(h) > 20

    def test_hash_is_not_deterministic(self) -> None:
        # bcrypt добавляет соль → два хеша одного пароля разные
        assert hash_password("secret123") != hash_password("secret123")

    def test_verify_correct_password(self) -> None:
        h = hash_password("secret123")
        assert verify_password("secret123", h) is True

    def test_verify_wrong_password(self) -> None:
        h = hash_password("secret123")
        assert verify_password("wrong", h) is False

    def test_verify_with_garbage_hash_returns_false(self) -> None:
        # Не должно бросать — только вернуть False
        assert verify_password("secret123", "not-a-bcrypt-hash") is False

    def test_verify_with_empty_hash_returns_false(self) -> None:
        assert verify_password("secret123", "") is False


# ===========================================================================
# JWT
# ===========================================================================

class TestJWT:
    def test_access_token_roundtrip(self) -> None:
        token = create_access_token("user-123")
        payload = decode_token(token, expected_type="access")
        assert payload["sub"] == "user-123"
        assert payload["type"] == "access"

    def test_refresh_token_roundtrip(self) -> None:
        token = create_refresh_token("user-123")
        payload = decode_token(token, expected_type="refresh")
        assert payload["sub"] == "user-123"
        assert payload["type"] == "refresh"

    def test_access_token_rejected_as_refresh(self) -> None:
        token = create_access_token("user-123")
        with pytest.raises(JWTError):
            decode_token(token, expected_type="refresh")

    def test_refresh_token_rejected_as_access(self) -> None:
        token = create_refresh_token("user-123")
        with pytest.raises(JWTError):
            decode_token(token, expected_type="access")

    def test_tampered_token_rejected(self) -> None:
        token = create_access_token("user-123")
        tampered = token[:-5] + "XXXXX"
        with pytest.raises(JWTError):
            decode_token(tampered)

    def test_token_signed_with_wrong_key_rejected(self) -> None:
        with patch("app.core.security.get_settings") as mock_settings:
            mock_settings.return_value.jwt_secret_key = "different-key"
            mock_settings.return_value.jwt_algorithm = "HS256"
            token = _create_token("user-123", "access", timedelta(minutes=5))

        # Восстанавливаем нормальный settings — токен подписан другим ключом
        with pytest.raises(JWTError):
            decode_token(token, expected_type="access")

    def test_expired_token_rejected(self) -> None:
        token = _create_token("user-123", "access", timedelta(seconds=-1))
        with pytest.raises(JWTError):
            decode_token(token, expected_type="access")