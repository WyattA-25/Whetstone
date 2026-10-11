"""Token verification tests with a locally generated RSA key (no network, no real credentials)."""
import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from whetstone.auth import AuthError, verify

ISS, AUD = "https://cognito-idp.us-east-1.amazonaws.com/us-east-1_TEST", "test-client"
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTHER = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def token(key=KEY, **over):
    now = int(time.time())
    claims = {"sub": "user-123", "email": "a@example.test", "aud": AUD, "iss": ISS, "token_use": "id",
              "iat": now, "exp": now + 600} | over
    return jwt.encode(claims, key, algorithm="RS256")


def check(t):
    return verify(t, signing_key=KEY.public_key(), issuer=ISS, audience=AUD)


def test_valid_token():
    assert check(token())["sub"] == "user-123"


@pytest.mark.parametrize("bad", [
    token(key=OTHER),                       # forged signature
    token(aud="someone-else"),              # wrong app client
    token(iss="https://evil.example"),      # wrong issuer
    token(token_use="access"),              # access token instead of ID token
    token(exp=int(time.time()) - 10),       # expired
    "not-a-jwt",
    "",
])
def test_rejected_tokens(bad):
    with pytest.raises(AuthError):
        check(bad)


def test_unsigned_token_rejected():
    t = jwt.encode({"sub": "x", "aud": AUD, "iss": ISS, "token_use": "id", "iat": 1, "exp": 2**31}, None,
                   algorithm="none")
    with pytest.raises(AuthError):
        check(t)
