"""Customer sign-in with Amazon Cognito. A customer's Cognito `sub` is their billing identity (customer_id).

- login(): USER_PASSWORD_AUTH against the app client (no client secret); returns the ID token to the browser.
- verify(): checks the ID token's RS256 signature against the pool's JWKS, plus issuer, audience (our app
  client), token_use == "id", and expiry. Only then is the `sub` trusted.
Passwords are never logged or stored by Whetstone; Cognito holds them.
"""
from __future__ import annotations

import os
import threading

import boto3
import jwt
from dotenv import load_dotenv

load_dotenv()

REGION = os.getenv("AWS_REGION", "us-east-1")
POOL_ID = os.getenv("COGNITO_USER_POOL_ID", "")
CLIENT_ID = os.getenv("COGNITO_CLIENT_ID", "")
ISSUER = f"https://cognito-idp.{REGION}.amazonaws.com/{POOL_ID}"

_jwks: jwt.PyJWKClient | None = None
_lock = threading.Lock()


class AuthError(Exception):
    pass


def _jwks_client() -> jwt.PyJWKClient:
    global _jwks
    with _lock:
        if _jwks is None:
            _jwks = jwt.PyJWKClient(f"{ISSUER}/.well-known/jwks.json", cache_keys=True)
        return _jwks


def verify(token: str, *, signing_key=None, issuer: str = ISSUER, audience: str = CLIENT_ID) -> dict:
    """Returns the verified claims ({"sub", "email", ...}) or raises AuthError."""
    if not token:
        raise AuthError("not signed in")
    try:
        key = signing_key or _jwks_client().get_signing_key_from_jwt(token).key
        claims = jwt.decode(token, key, algorithms=["RS256"], audience=audience, issuer=issuer,
                            options={"require": ["exp", "iat", "sub", "aud", "iss", "token_use"]})
    except jwt.ExpiredSignatureError:
        raise AuthError("session expired; sign in again") from None
    except Exception:
        raise AuthError("invalid session token") from None
    if claims.get("token_use") != "id":
        raise AuthError("wrong token type")
    return claims


def login(email: str, password: str) -> dict:
    if not (POOL_ID and CLIENT_ID):
        raise AuthError("sign-in is not configured (run python -m whetstone.aws_setup)")
    idp = boto3.client("cognito-idp", region_name=REGION)
    try:
        r = idp.initiate_auth(ClientId=CLIENT_ID, AuthFlow="USER_PASSWORD_AUTH",
                              AuthParameters={"USERNAME": email, "PASSWORD": password})
    except idp.exceptions.NotAuthorizedException:
        raise AuthError("wrong email or password") from None
    except idp.exceptions.PasswordResetRequiredException:
        raise AuthError("password reset required") from None
    except Exception as e:  # never echo request contents (they include the password)
        raise AuthError(f"sign-in failed ({type(e).__name__})") from None
    if "AuthenticationResult" not in r:
        raise AuthError(f"additional step required: {r.get('ChallengeName', 'unknown')}")
    res = r["AuthenticationResult"]
    claims = verify(res["IdToken"])
    return {"id_token": res["IdToken"], "expires_in": res["ExpiresIn"], "email": claims.get("email"),
            "customer_id": claims["sub"]}


def _idp():
    if not (POOL_ID and CLIENT_ID):
        raise AuthError("sign-up is not configured (run python -m whetstone.aws_setup)")
    return boto3.client("cognito-idp", region_name=REGION)


def sign_up(email: str, password: str) -> dict:
    """Self sign-up. Cognito emails a 6-digit code; the account is usable after confirm_sign_up()."""
    idp = _idp()
    try:
        r = idp.sign_up(ClientId=CLIENT_ID, Username=email, Password=password,
                        UserAttributes=[{"Name": "email", "Value": email}])
    except idp.exceptions.UsernameExistsException:
        raise AuthError("an account with this email already exists; sign in instead") from None
    except idp.exceptions.InvalidPasswordException:
        raise AuthError("password must be at least 10 characters with lowercase letters and a number") from None
    except Exception as e:  # never echo the request (it holds the password)
        raise AuthError(f"sign-up failed ({type(e).__name__})") from None
    return {"confirmed": r.get("UserConfirmed", False),
            "sent_to": r.get("CodeDeliveryDetails", {}).get("Destination")}


def confirm_sign_up(email: str, code: str) -> None:
    idp = _idp()
    try:
        idp.confirm_sign_up(ClientId=CLIENT_ID, Username=email, ConfirmationCode=code.strip())
    except (idp.exceptions.CodeMismatchException, idp.exceptions.ExpiredCodeException):
        raise AuthError("that code is wrong or expired; request a new one") from None
    except Exception as e:  # noqa: BLE001
        raise AuthError(f"confirmation failed ({type(e).__name__})") from None


def resend_code(email: str) -> None:
    try:
        _idp().resend_confirmation_code(ClientId=CLIENT_ID, Username=email)
    except Exception as e:  # noqa: BLE001
        raise AuthError(f"could not resend the code ({type(e).__name__})") from None
