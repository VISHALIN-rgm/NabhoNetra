#!/usr/bin/env bash
# Publishes the website to AWS Amplify Hosting (https, CDN, free domain *.amplifyapp.com).
# Needs docker (builds the website; CloudShell has it) and the aws CLI. No GitHub needed.
#   API_URL=https://xxxx.us-west-2.awsapprunner.com bash deploy-frontend.sh
# Optional: REGION (us-west-2), AMPLIFY_APP (nabhonetra), AMPLIFY_BRANCH (main).
# Prints progress to the screen and, as its last act, the website address on stdout.
set -euo pipefail
exec 3>&1 1>&2                      # everything below prints to the screen; only the final address goes to stdout
: "${API_URL:?Set API_URL to the API address, for example https://xxxx.us-west-2.awsapprunner.com}"
API_URL="${API_URL%/}"; REGION="${REGION:-us-west-2}"; APP_NAME="${AMPLIFY_APP:-nabhonetra}"; BRANCH="${AMPLIFY_BRANCH:-main}"
[[ "$API_URL" == https://* ]] || { echo "API_URL must start with https://"; exit 1; }
cd "$(dirname "$0")/.."

echo "Building the website (it will call $API_URL)"
rm -rf .site && mkdir -p .site/dist
docker build --target web --build-arg "VITE_API_URL=$API_URL" -t nabhonetra-web .
CID=$(docker create nabhonetra-web); docker cp "$CID:/w/dist/." .site/dist; docker rm "$CID" >/dev/null
(cd .site/dist && python3 -m zipfile -c ../site.zip *)

APP_ID=$(aws amplify list-apps --region "$REGION" --query "apps[?name=='$APP_NAME'].appId | [0]" --output text)
if [[ -z "$APP_ID" || "$APP_ID" == "None" ]]; then
  APP_ID=$(aws amplify create-app --region "$REGION" --name "$APP_NAME" --platform WEB --query app.appId --output text)
fi
aws amplify get-branch --region "$REGION" --app-id "$APP_ID" --branch-name "$BRANCH" >/dev/null 2>&1 || \
  aws amplify create-branch --region "$REGION" --app-id "$APP_ID" --branch-name "$BRANCH" >/dev/null

# Browser protections. The page may only load its own scripts and talk to its own API; no other site can frame it.
HEADERS="customHeaders:
  - pattern: '**'
    headers:
      - key: 'Content-Security-Policy'
        value: \"default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src https://fonts.gstatic.com; img-src 'self' data: blob: https:; connect-src 'self' $API_URL; frame-ancestors 'none'; base-uri 'self'; form-action 'self'; object-src 'none'\"
      - key: 'X-Content-Type-Options'
        value: 'nosniff'
      - key: 'X-Frame-Options'
        value: 'DENY'
      - key: 'Referrer-Policy'
        value: 'strict-origin-when-cross-origin'
      - key: 'Strict-Transport-Security'
        value: 'max-age=31536000; includeSubDomains'
      - key: 'Permissions-Policy'
        value: 'geolocation=(self), camera=(), microphone=()'
"
aws amplify update-app --region "$REGION" --app-id "$APP_ID" --custom-headers "$HEADERS" >/dev/null

echo "Uploading"
read -r JOB UPLOAD < <(aws amplify create-deployment --region "$REGION" --app-id "$APP_ID" --branch-name "$BRANCH" --query '[jobId,zipUploadUrl]' --output text)
curl -fsS -T .site/site.zip "$UPLOAD"
aws amplify start-deployment --region "$REGION" --app-id "$APP_ID" --branch-name "$BRANCH" --job-id "$JOB" >/dev/null
for _ in $(seq 1 60); do
  STATUS=$(aws amplify get-job --region "$REGION" --app-id "$APP_ID" --branch-name "$BRANCH" --job-id "$JOB" --query job.summary.status --output text)
  case "$STATUS" in SUCCEED) break;; FAILED|CANCELLED) echo "Amplify deployment $STATUS. See the Amplify console, app $APP_NAME, for the log."; exit 1;; esac
  sleep 10
done
[[ "$STATUS" == "SUCCEED" ]] || { echo "Amplify deployment is still running after 10 minutes. Check the Amplify console."; exit 1; }
DOMAIN=$(aws amplify get-app --region "$REGION" --app-id "$APP_ID" --query app.defaultDomain --output text)
echo "Website published."
echo "https://$BRANCH.$DOMAIN" >&3
