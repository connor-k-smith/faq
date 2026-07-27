import pytest

from app.domain.tokens import SecureTokenGenerator


def test_token_generator_enforces_minimum_entropy() -> None:
    generator = SecureTokenGenerator()

    with pytest.raises(ValueError, match="128 bits"):
        generator.urlsafe(15)

    assert len(generator.urlsafe(16)) >= 22
