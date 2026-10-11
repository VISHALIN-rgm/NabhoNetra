"""Runs the same end-to-end checks against DynamoDB and S3, using a simulated AWS (moto). Run: pip install "moto[dynamodb,s3]"; python dynamo_test.py"""
import os
os.environ.update(STORE="dynamodb", DDB_PREFIX="nn", STORE_REGION="us-east-1", SNAPSHOT_BUCKET="nabhonetra-test-bucket",
                  AWS_ACCESS_KEY_ID="x", AWS_SECRET_ACCESS_KEY="x", AWS_DEFAULT_REGION="us-east-1")
import boto3
from moto import mock_aws

with mock_aws():
    boto3.client("s3", region_name="us-east-1").create_bucket(Bucket=os.environ["SNAPSHOT_BUCKET"])
    import store
    store.create_tables()
    import importlib
    importlib.import_module("smoke_test")   # runs every check against DynamoDB + S3
print("DynamoDB + S3 checks passed")
