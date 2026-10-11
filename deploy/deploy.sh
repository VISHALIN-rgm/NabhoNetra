#!/usr/bin/env bash
# For AWS CloudShell (or any Linux/macOS shell with docker and the aws CLI). No Docker on your own PC needed.
#   cd cropfire-agent/deploy
#   read -rsp "FIRMS key: " FIRMS_KEY; echo; export FIRMS_KEY
#   export ADMIN_TOKEN=$(openssl rand -hex 24); echo "SAVE THIS ADMIN TOKEN: $ADMIN_TOKEN"
#   DELIVERY_MODE=log bash deploy.sh
# Optional settings (environment variables): OPS_EMAIL, SES_FROM, REGION (default us-west-2), STACK (default nabhonetra),
# PUBLIC_URL (your own domain), DELIVERY_MODE (live or log; log = nothing is sent, for a first try-out),
# CORS_ORIGINS (website addresses allowed to call the API when you host the website yourself, comma separated),
# FRONTEND (apprunner = App Runner also serves the website, the default; amplify = website on AWS Amplify Hosting, API on App Runner).
set -euo pipefail
: "${FIRMS_KEY:?Set FIRMS_KEY first}"; : "${ADMIN_TOKEN:?Set ADMIN_TOKEN first}"
OPS_EMAIL="${OPS_EMAIL:-}"; SES_FROM="${SES_FROM:-}"; REGION="${REGION:-us-west-2}"; STACK="${STACK:-nabhonetra}"
PUBLIC_URL="${PUBLIC_URL:-}"; DELIVERY_MODE="${DELIVERY_MODE:-live}"; FRONTEND="${FRONTEND:-apprunner}"; CORS_ORIGINS="${CORS_ORIGINS:-}"
[[ "$ADMIN_TOKEN" =~ ^[A-Za-z0-9_-]{16,}$ ]] || { echo "ADMIN_TOKEN must be 16+ characters: letters, digits, - or _"; exit 1; }
[[ "$FRONTEND" == "apprunner" || "$FRONTEND" == "amplify" ]] || { echo "FRONTEND must be apprunner or amplify"; exit 1; }
[[ "$DELIVERY_MODE" == "live" || "$DELIVERY_MODE" == "log" ]] || { echo "DELIVERY_MODE must be live or log"; exit 1; }

cd "$(dirname "$0")"
ACCT=$(aws sts get-caller-identity --query Account --output text)
REGISTRY="$ACCT.dkr.ecr.$REGION.amazonaws.com"
aws ecr describe-repositories --repository-names nabhonetra --region "$REGION" >/dev/null 2>&1 || aws ecr create-repository --repository-name nabhonetra --region "$REGION" >/dev/null
aws ecr get-login-password --region "$REGION" | docker login --username AWS --password-stdin "$REGISTRY"
IMAGE="$REGISTRY/nabhonetra:$(date +%Y%m%d%H%M%S)"
docker build -t "$IMAGE" ..
docker push "$IMAGE"

deploy_stack() {
  aws cloudformation deploy --template-file apprunner.yaml --stack-name "$STACK" --region "$REGION" --capabilities CAPABILITY_IAM \
    --parameter-overrides "ImageUri=$IMAGE" "FirmsKey=$FIRMS_KEY" "AdminToken=$ADMIN_TOKEN" "OpsEmail=$OPS_EMAIL" "SesFrom=$SES_FROM" \
    "BedrockRegion=$REGION" "PublicUrl=$1" "CorsOrigins=$CORS_ORIGINS" "DeliveryMode=$DELIVERY_MODE" \
    || { echo "CloudFormation deploy failed. Open the CloudFormation console, Events tab, to see why."; exit 1; }
}
site_url() { aws cloudformation describe-stacks --stack-name "$STACK" --region "$REGION" --query "Stacks[0].Outputs[?OutputKey=='SiteUrl'].OutputValue" --output text; }

deploy_stack "$PUBLIC_URL"
API=$(site_url)
if [[ "$FRONTEND" == "amplify" ]]; then
  SITE=$(API_URL="$API" REGION="$REGION" bash ./deploy-frontend.sh)
  CORS_ORIGINS="$SITE${PUBLIC_URL:+,$PUBLIC_URL}${CORS_ORIGINS:+,$CORS_ORIGINS}"
  echo "Pointing the API at the website address (one more update, a few minutes)"; deploy_stack "${PUBLIC_URL:-$SITE}"
else
  SITE="$API"
  if [[ -z "$PUBLIC_URL" ]]; then echo "Setting PUBLIC_URL to $SITE (one more update, a few minutes)"; deploy_stack "$SITE"; fi
fi
echo; echo "Website: $SITE"; echo "API:     $API"
echo "Next: create the first administrator (see README, 'First administrator on AWS')."
