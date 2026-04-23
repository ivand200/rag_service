from __future__ import annotations

import base64
import json
import time
from collections.abc import Sequence
from dataclasses import dataclass

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

from app.config import Settings

CLERK_TOKEN_ALGORITHM = "RS256"


@dataclass(slots=True, frozen=True)
class AuthenticatedUser:
    clerk_user_id: str
    session_id: str | None = None


class AuthenticationError(Exception):
    """Raised when a request token is missing required auth guarantees."""


class AuthenticationConfigurationError(Exception):
    """Raised when backend auth verification is not configured."""


def verify_clerk_token(*, token: str, settings: Settings) -> AuthenticatedUser:
    if settings.clerk_jwt_public_key is None:
        raise AuthenticationConfigurationError("CLERK_JWT_PUBLIC_KEY is not configured")

    claims = _decode_and_verify_token(token=token, public_key_pem=settings.clerk_jwt_public_key)

    clerk_user_id = claims.get("sub")
    if not isinstance(clerk_user_id, str) or not clerk_user_id.strip():
        raise AuthenticationError("authentication token is missing a subject")

    _validate_authorized_party(
        authorized_party=claims.get("azp"),
        allowed_parties=settings.clerk_authorized_parties,
    )

    session_id = claims.get("sid")
    if session_id is not None and not isinstance(session_id, str):
        session_id = str(session_id)

    return AuthenticatedUser(
        clerk_user_id=clerk_user_id,
        session_id=session_id,
    )


def _validate_authorized_party(
    *,
    authorized_party: object,
    allowed_parties: Sequence[str],
) -> None:
    if authorized_party is None:
        return
    if not isinstance(authorized_party, str) or not authorized_party.strip():
        raise AuthenticationError("authentication token has an invalid authorized party")

    normalized_authorized_party = authorized_party.rstrip("/")
    if normalized_authorized_party not in allowed_parties:
        raise AuthenticationError("authentication token was issued for another origin")


def _decode_and_verify_token(*, token: str, public_key_pem: str) -> dict[str, object]:
    try:
        encoded_header, encoded_payload, encoded_signature = token.split(".")
    except ValueError as exc:
        raise AuthenticationError("authentication token is malformed") from exc

    header = _decode_json_segment(encoded_header)
    payload = _decode_json_segment(encoded_payload)

    algorithm = header.get("alg")
    if algorithm != CLERK_TOKEN_ALGORITHM:
        raise AuthenticationError("authentication token uses an unsupported algorithm")

    signing_input = f"{encoded_header}.{encoded_payload}".encode("ascii")
    signature = _decode_base64url(encoded_signature)

    public_key = serialization.load_pem_public_key(public_key_pem.encode("utf-8"))
    try:
        public_key.verify(signature, signing_input, padding.PKCS1v15(), hashes.SHA256())
    except InvalidSignature as exc:
        raise AuthenticationError("authentication token signature is invalid") from exc

    _validate_registered_claims(payload)
    return payload


def _decode_json_segment(segment: str) -> dict[str, object]:
    try:
        decoded = _decode_base64url(segment)
        data = json.loads(decoded)
    except (ValueError, json.JSONDecodeError) as exc:
        raise AuthenticationError("authentication token is malformed") from exc
    if not isinstance(data, dict):
        raise AuthenticationError("authentication token is malformed")
    return data


def _decode_base64url(value: str) -> bytes:
    padding_length = (-len(value)) % 4
    padded_value = f"{value}{'=' * padding_length}"
    try:
        return base64.urlsafe_b64decode(padded_value.encode("ascii"))
    except (ValueError, UnicodeEncodeError) as exc:
        raise AuthenticationError("authentication token is malformed") from exc


def _validate_registered_claims(claims: dict[str, object]) -> None:
    exp = _read_numeric_claim(claims, "exp")
    nbf = _read_numeric_claim(claims, "nbf")
    now = time.time()
    if exp <= now:
        raise AuthenticationError("authentication token has expired")
    if nbf > now:
        raise AuthenticationError("authentication token is not active yet")


def _read_numeric_claim(claims: dict[str, object], claim_name: str) -> float:
    value = claims.get(claim_name)
    if not isinstance(value, int | float):
        raise AuthenticationError(f"authentication token is missing {claim_name}")
    return float(value)
