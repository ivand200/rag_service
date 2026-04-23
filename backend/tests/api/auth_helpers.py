from __future__ import annotations

import base64
import json
import time

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

TEST_CLERK_PUBLIC_KEY = """-----BEGIN PUBLIC KEY-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEA+Wsc2VjC120SWn3xMuGE
BGcvNbXtXQhrochf/VjaryK3YKWcg1rA9ZUUdxQT5/H5x1SbGN35Sd+VOmV6n/0h
/ePz4YS2Pup+ZzxJUcz/RuAKOiAzdybTJ8vacZWy8TVoJ7Jihn0fPM7JiZ7kTG7s
aFoCtqTst1esgL8MdmZP1yVUiIFqgv4qGJzI4MSY9WbIXo/50j8w0bSoTrmY5cgi
5WuHR+mekKZxgfl756PTpAzeRHMEiFfzriB02musHKyKRO105al8SNQYSEcFRCxm
9PW6vjU43R0QuuExq4t7Eljx/53Gq7+VK3q4Hv+/S7Aw1OISG40lntG5SwudqkaG
iwIDAQAB
-----END PUBLIC KEY-----"""

TEST_CLERK_PRIVATE_KEY = """-----BEGIN PRIVATE KEY-----
MIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQD5axzZWMLXbRJa
ffEy4YQEZy81te1dCGuhyF/9WNqvIrdgpZyDWsD1lRR3FBPn8fnHVJsY3flJ35U6
ZXqf/SH94/PhhLY+6n5nPElRzP9G4Ao6IDN3JtMny9pxlbLxNWgnsmKGfR88zsmJ
nuRMbuxoWgK2pOy3V6yAvwx2Zk/XJVSIgWqC/ioYnMjgxJj1Zshej/nSPzDRtKhO
uZjlyCLla4dH6Z6QpnGB+Xvno9OkDN5EcwSIV/OuIHTaa6wcrIpE7XTlqXxI1BhI
RwVELGb09bq+NTjdHRC64TGri3sSWPH/ncarv5Urerge/79LsDDU4hIbjSWe0blL
C52qRoaLAgMBAAECggEAAV3D17DzyEhRrGs6MgQoO/nwuUOY3ESailVVqUaeVA1F
oeLmW5XYrr+1T/2tKj0aGCxveRBmODBgWeSKamvxjrl78YVPlkKklJ4w7KDJ2TKK
+8yHW6S7zWEBflPKmiWnv2frwD7ZN/UOB5H2QDDvXJb5otR+c3aofEAPqmpfD5ei
/S73OL+LAmZ7RT7slsWTmakjHpx2gsHKf0yNjr+3A20m39GPXHMgx3vgCyOfZpKd
4v7QA8NOHmwY5xcQVhcmQkECnzGbtXUgnehrsBaAW1eNgiR0qnnXP6KWOPmWuBUD
+CdNPRmvhrAzow4T1rEVSZt2OGfEOcYqkljPWM10EQKBgQD+S6Wl/TXnywokWcvm
BfzltRVUEJNGNsEKseS3iuA+w9Frdu8vh9SeLG+QcyrhPs+lRmaLhIzFisK6G46O
6nTcBP4m9qiUNc3EokcQkO4KbKatNK7GzJ/QeqEiFe92tqyMzY4RDN/oHigygzpi
6WFe31PwWT+j4eAioQYTTFU04wKBgQD7FxjN/yz6UjbjeUiu35uJWznprgCv+ZPh
SspJQFO8z3qEqXLRbyfyRhjgCQibQkkEgAvAoHIgyKY7rnyK5v8Y7QY2QY7hnA4e
JDC8ANXu0/YF6Rrnxfdi2mU+P3W6bmcwTmRJqDKpOE1MYMm3HHsL8L4ILrO99yNC
J0DyCqdAOQKBgEdIZ0fPYgP224HzFgAF3614hGELQG1nPdfEpCt7J38Qnyyzqzq0
pbotFJz2W6fGVqiqwmYLovZg/lLzFJQlTtq6H5BGhlz9dA/RuYAAUGnlqRdWdEPP
6mCjb3XBll29uULDADbxV/aWNYhrVruRVjUk/z+ZlQhYcd7jKnPQavYnAoGAeCAy
s8sTP6c5r1aFGXTNOse0S0H9/jLPNwfLA4SNC1XP7cwLrHsbh2NV30kzHuR1fnus
I7ofH+Qe84qk9udQwCIVyLtQmktIzc7OqgNUVnB90ZIWVzB1DIwjx8YgktLi909p
13tq0V6oTJQ5rSspCytgHxYI1Cd6bNnOzn2eSrECgYEAq8iutGjXRvLkQibyr+j2
VRNtZbP0gTwQYSgkjaFs9K74zgjY9dflqgqYkFAUrtDSSQjahlU94W+ulqhX3XCH
DpsLqRBc7GXcK0WME8uF9wMkYdHGBALbIUZBytvLARS13elw2JVkfCjsacNPZuRb
E4dIGHHrgltIavKZickAbqQ=
-----END PRIVATE KEY-----"""


def auth_headers(
    *,
    user_id: str = "user_123",
    authorized_party: str = "http://localhost:5173",
    session_id: str = "sess_123",
) -> dict[str, str]:
    now = int(time.time())
    token = _encode_rs256_token(
        {
            "sub": user_id,
            "sid": session_id,
            "azp": authorized_party,
            "nbf": now,
            "exp": now + (5 * 60),
        }
    )
    return {"Authorization": f"Bearer {token}"}


def _encode_rs256_token(payload: dict[str, object]) -> str:
    header = {"alg": "RS256", "typ": "JWT"}
    encoded_header = _base64url_encode(json.dumps(header, separators=(",", ":")).encode("utf-8"))
    encoded_payload = _base64url_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signing_input = f"{encoded_header}.{encoded_payload}".encode("ascii")
    private_key = serialization.load_pem_private_key(
        TEST_CLERK_PRIVATE_KEY.encode("utf-8"),
        password=None,
    )
    signature = private_key.sign(signing_input, padding.PKCS1v15(), hashes.SHA256())
    encoded_signature = _base64url_encode(signature)
    return f"{encoded_header}.{encoded_payload}.{encoded_signature}"


def _base64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")
