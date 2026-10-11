#!/usr/bin/env bash
# Redeploy the public, read-only Whetstone dashboard to AWS Lambda (Function URL). Run from the repo root.
# First-time setup (ECR repo, IAM role WhetstoneWebLambda with logs + read-only whetstone-runs, function,
# public Function URL) was done once; this script rebuilds and pushes the image and updates the function.
# Note: App Runner was the plan, but this account returns SubscriptionRequiredException for it.
set -euo pipefail
AWS="${AWS_CLI:-aws}"; REG="${AWS_REGION:-us-east-1}"
ACCT=$("$AWS" sts get-caller-identity --query Account --output text)
IMG="$ACCT.dkr.ecr.$REG.amazonaws.com/whetstone-web:lambda"
docker build --platform linux/amd64 --provenance=false -f Dockerfile.lambda -t "$IMG" .
"$AWS" ecr get-login-password --region "$REG" | docker login --username AWS --password-stdin "$ACCT.dkr.ecr.$REG.amazonaws.com"
docker push "$IMG"
"$AWS" lambda update-function-code --function-name whetstone-web --image-uri "$IMG" --region "$REG" >/dev/null
"$AWS" lambda wait function-updated-v2 --function-name whetstone-web --region "$REG"
"$AWS" lambda get-function-url-config --function-name whetstone-web --region "$REG" --query FunctionUrl --output text
