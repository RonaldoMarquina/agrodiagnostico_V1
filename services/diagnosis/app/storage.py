"""Bounded authorized bucket probe, no object mutation during readiness."""
import json
import os
from pathlib import Path
import boto3
from botocore.config import Config


def storage_ready():
    try:
        credentials = json.loads(Path(os.environ["S3_CREDENTIALS_FILE"]).read_text())
        client = boto3.client("s3", endpoint_url=os.environ["S3_ENDPOINT_URL"],
                              region_name=os.environ["S3_REGION"],
                              aws_access_key_id=credentials["access_key"],
                              aws_secret_access_key=credentials["secret_key"],
                              config=Config(connect_timeout=2, read_timeout=2,
                                            retries={"max_attempts": 0},
                                            s3={"addressing_style": "path"}))
        try:
            client.head_bucket(Bucket=os.environ["S3_BUCKET"])
        finally:
            client.close()
        return True
    except Exception:
        return False
