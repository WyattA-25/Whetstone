"""Onboard a customer: create their Cognito sign-in (admin-created; B2B onboarding).

Usage:  python -m whetstone.customers add <email> [--plan founding|standard] [--copy-demo-keys]

The password is typed into a hidden prompt in YOUR terminal (getpass) and sent straight to Cognito; it is
never printed, logged, or stored by Whetstone. --copy-demo-keys re-encrypts the legacy "demo" customer's
AI-provider keys under the new customer (KMS encryption context is per customer, so blobs can't be copied).
"""
from __future__ import annotations

import argparse
import getpass
import sys

import boto3

from .accounts import Accounts
from .auth import POOL_ID, REGION


def add(email: str, plan: str, copy_demo_keys: bool) -> None:
    idp = boto3.client("cognito-idp", region_name=REGION)
    try:
        idp.admin_create_user(UserPoolId=POOL_ID, Username=email, MessageAction="SUPPRESS",
                              UserAttributes=[{"Name": "email", "Value": email},
                                              {"Name": "email_verified", "Value": "true"}])
        print(f"created {email}")
    except idp.exceptions.UsernameExistsException:
        print(f"{email} already exists; setting a new password")
    pw = getpass.getpass("Choose a password (min 10 chars, letters + a number): ")
    if pw != getpass.getpass("Repeat password: "):
        sys.exit("passwords don't match; nothing changed")
    idp.admin_set_user_password(UserPoolId=POOL_ID, Username=email, Password=pw, Permanent=True)
    sub = next(a["Value"] for a in idp.admin_get_user(UserPoolId=POOL_ID, Username=email)["UserAttributes"]
               if a["Name"] == "sub")
    acc = Accounts()
    acc.set_plan(sub, plan)
    print(f"customer_id (Cognito sub): {sub} | plan: {plan}")
    if copy_demo_keys:
        for k in acc.list_keys("demo"):
            sec = acc.key_secret("demo", k["key_id"])
            acc.add_key(sub, provider=sec["provider"], base_url=sec["base_url"], model=sec["model"],
                        api_key=sec["api_key"], price_in_per_m=sec["price_in_per_m"],
                        price_out_per_m=sec["price_out_per_m"])
            print(f"re-encrypted key {sec['provider']} / {sec['model']} for this customer")
    print("Done. Sign in on the Account & runs tab.")


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("add")
    a.add_argument("email")
    a.add_argument("--plan", default="founding", choices=["founding", "standard"])
    a.add_argument("--copy-demo-keys", action="store_true")
    args = ap.parse_args()
    if not POOL_ID:
        sys.exit("COGNITO_USER_POOL_ID missing: run python -m whetstone.aws_setup")
    add(args.email, args.plan, args.copy_demo_keys)


if __name__ == "__main__":
    main()
