import secrets


class SecureTokenGenerator:
    def urlsafe(self, byte_count: int = 32) -> str:
        if byte_count < 16:
            raise ValueError("respondent tokens require at least 128 bits of entropy")
        return secrets.token_urlsafe(byte_count)
