# Run from the deploy folder:  .\deploy.ps1 -FirmsKey KEY -AdminToken LONG_TOKEN -OpsEmail you@example.com -SesFrom verified@example.com
# First try-out with nothing really sent (codes go to the logs, not to phones): add  -DeliveryMode log
# The script deploys, reads the site address, then updates the service once more so response links use that address (or pass -PublicUrl for your own domain).
param(
  [Parameter(Mandatory=$true)][string]$FirmsKey,
  [Parameter(Mandatory=$true)][string]$AdminToken,
  [string]$OpsEmail = "", [string]$SesFrom = "", [string]$Region = "us-west-2", [string]$Stack = "nabhonetra",
  [string]$PublicUrl = "", [ValidateSet("live","log")][string]$DeliveryMode = "live"
)
$ErrorActionPreference = "Stop"
if ($AdminToken -notmatch '^[A-Za-z0-9_-]{16,}$') { throw "AdminToken must be 16+ characters: letters, digits, - or _" }
$acct = aws sts get-caller-identity --query Account --output text
$registry = "$acct.dkr.ecr.$Region.amazonaws.com"
$ErrorActionPreference = "Continue"
aws ecr describe-repositories --repository-names nabhonetra --region $Region *> $null
$repoExists = ($LASTEXITCODE -eq 0)
$ErrorActionPreference = "Stop"
if (-not $repoExists) { aws ecr create-repository --repository-name nabhonetra --region $Region | Out-Null }
aws ecr get-login-password --region $Region | docker login --username AWS --password-stdin $registry
$image = "$registry/nabhonetra:" + (Get-Date -Format "yyyyMMddHHmmss")
docker build -t $image ..
docker push $image
function Deploy-Stack([string]$url) {
  aws cloudformation deploy --template-file apprunner.yaml --stack-name $Stack --region $Region --capabilities CAPABILITY_IAM `
    --parameter-overrides "ImageUri=$image" "FirmsKey=$FirmsKey" "AdminToken=$AdminToken" "OpsEmail=$OpsEmail" "SesFrom=$SesFrom" "BedrockRegion=$Region" "PublicUrl=$url" "DeliveryMode=$DeliveryMode"
  if ($LASTEXITCODE -ne 0) { throw "CloudFormation deploy failed. Open the CloudFormation console, Events tab, to see why." }
}
function Get-SiteUrl { aws cloudformation describe-stacks --stack-name $Stack --region $Region --query "Stacks[0].Outputs[?OutputKey=='SiteUrl'].OutputValue" --output text }

Deploy-Stack $PublicUrl
$site = Get-SiteUrl
if (-not $PublicUrl) { Write-Host "Setting PublicUrl to $site (one more update, a few minutes)"; Deploy-Stack $site }
Write-Host ""; Write-Host "Live at: $site"
Write-Host "Next: create the first administrator (see README, 'First administrator on AWS')."
