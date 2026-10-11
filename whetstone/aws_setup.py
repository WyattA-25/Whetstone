"""Create Whetstone's DynamoDB tables (idempotent). Usage: python -m whetstone.aws_setup

- whetstone-runs:     run history (runs, rounds, candidates, lessons, latest state). Key: run_id + sk.
- whetstone-accounts: customers (plan, encrypted API keys, run counter, usage log). Key: customer_id + sk.
Both are on-demand ("PAY_PER_REQUEST"): no capacity to manage, billed per request (cents at our scale).
"""
from __future__ import annotations

import os

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


def main() -> None:
    region = os.getenv("AWS_REGION", "us-east-1")
    ddb = boto3.client("dynamodb", region_name=region)
    ident = boto3.client("sts", region_name=region).get_caller_identity()
    print(f"AWS account {ident['Account']} ({ident['Arn'].split('/')[-1]}), region {region}")
    for name, pk in ((RUNS_TABLE, "run_id"), (ACCOUNTS_TABLE, "customer_id")):
        print(f"  {name}: {ensure_table(ddb, name, pk)}")


if __name__ == "__main__":
    main()
