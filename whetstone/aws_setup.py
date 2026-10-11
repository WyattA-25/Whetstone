"""Create Whetstone's DynamoDB tables (idempotent). Usage: python -m whetstone.aws_setup

- whetstone-runs:     run history (runs, rounds, candidates, lessons, latest state). Key: run_id + sk.
- whetstone-accounts: customers (plan, encrypted API keys, run counter, usage log). Key: customer_id + sk.
Both are on-demand ("PAY_PER_REQUEST"): no capacity to manage, billed per request (cents at our scale).
- KMS key alias/whetstone-customer-keys: encrypts customers' AI-provider API keys at rest (~$1/month).
- Cognito user pool whetstone-customers + app client whetstone-web: customer sign-in. A customer's Cognito
  `sub` is their billing identity. Self sign-up with an emailed verification code (or admin-created).
"""
from __future__ import annotations

import os
from pathlib import Path

import boto3
from dotenv import load_dotenv

from .store import ACCOUNTS_TABLE, RUNS_TABLE

load_dotenv()


def ensure_table(ddb, name: str, pk: str) -> str:
    existing = ddb.list_tables()["TableNames"]
    if name in existing:
        return "exists"
    ddb.create_table(TableName=name, BillingMode="PAY_PER_REQUEST",
                     AttributeDefinitions=[{"AttributeName": pk, "AttributeType": "S"},
                                           {"AttributeName": "sk", "AttributeType": "S"}],
                     KeySchema=[{"AttributeName": pk, "KeyType": "HASH"}, {"AttributeName": "sk", "KeyType": "RANGE"}],
                     Tags=[{"Key": "project", "Value": "whetstone"}])
    ddb.get_waiter("table_exists").wait(TableName=name)
    return "created"


KMS_ALIAS = os.getenv("KMS_KEY_ALIAS", "alias/whetstone-customer-keys")


def ensure_kms_key(kms) -> str:
    aliases = {a["AliasName"]: a.get("TargetKeyId") for p in kms.get_paginator("list_aliases").paginate()
               for a in p["Aliases"]}
    if KMS_ALIAS in aliases and aliases[KMS_ALIAS]:
        return f"exists ({aliases[KMS_ALIAS]})"
    key = kms.create_key(Description="Whetstone: encrypts customer AI-provider API keys at rest",
                         KeyUsage="ENCRYPT_DECRYPT", Tags=[{"TagKey": "project", "TagValue": "whetstone"}])
    kid = key["KeyMetadata"]["KeyId"]
    kms.create_alias(AliasName=KMS_ALIAS, TargetKeyId=kid)
    kms.enable_key_rotation(KeyId=kid)
    return f"created ({kid}, yearly rotation on)"


def ensure_user_pool(idp) -> tuple[str, str]:
    pools = [p for p in idp.list_user_pools(MaxResults=60)["UserPools"] if p["Name"] == "whetstone-customers"]
    if pools:
        pool_id = pools[0]["Id"]
    else:
        pool_id = idp.create_user_pool(
            PoolName="whetstone-customers", UsernameAttributes=["email"], AutoVerifiedAttributes=["email"],
            AdminCreateUserConfig={"AllowAdminCreateUserOnly": False},   # self sign-up with email verification
            Policies={"PasswordPolicy": {"MinimumLength": 10, "RequireUppercase": False, "RequireLowercase": True,
                                         "RequireNumbers": True, "RequireSymbols": False}},
            UserPoolTags={"project": "whetstone"})["UserPool"]["Id"]
    clients = [c for c in idp.list_user_pool_clients(UserPoolId=pool_id, MaxResults=60)["UserPoolClients"]
               if c["ClientName"] == "whetstone-web"]
    if clients:
        client_id = clients[0]["ClientId"]
    else:
        client_id = idp.create_user_pool_client(
            UserPoolId=pool_id, ClientName="whetstone-web", GenerateSecret=False,
            ExplicitAuthFlows=["ALLOW_USER_PASSWORD_AUTH", "ALLOW_REFRESH_TOKEN_AUTH"],
            PreventUserExistenceErrors="ENABLED", IdTokenValidity=8, TokenValidityUnits={"IdToken": "hours"},
        )["UserPoolClient"]["ClientId"]
    return pool_id, client_id


def main() -> None:
    region = os.getenv("AWS_REGION", "us-east-1")
    ddb = boto3.client("dynamodb", region_name=region)
    ident = boto3.client("sts", region_name=region).get_caller_identity()
    print(f"AWS account {ident['Account']} ({ident['Arn'].split('/')[-1]}), region {region}")
    for name, pk in ((RUNS_TABLE, "run_id"), (ACCOUNTS_TABLE, "customer_id")):
        print(f"  {name}: {ensure_table(ddb, name, pk)}")
    print(f"  {KMS_ALIAS}: {ensure_kms_key(boto3.client('kms', region_name=region))}")
    pool_id, client_id = ensure_user_pool(boto3.client("cognito-idp", region_name=region))
    print(f"  cognito user pool: {pool_id}  app client: {client_id}")
    env = Path(".env")
    if env.exists() and "COGNITO_USER_POOL_ID" not in env.read_text(encoding="utf-8"):
        with env.open("a", encoding="utf-8") as f:   # ids are not secrets; written so the app can find them
            f.write(f"\n# --- Cognito (customer sign-in) ---\nCOGNITO_USER_POOL_ID={pool_id}\nCOGNITO_CLIENT_ID={client_id}\n")
        print("  wrote COGNITO_USER_POOL_ID / COGNITO_CLIENT_ID to .env")


if __name__ == "__main__":
    main()
