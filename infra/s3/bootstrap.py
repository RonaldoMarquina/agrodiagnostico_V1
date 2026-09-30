import json
import os
from pathlib import Path
import sys
import time
import boto3
from botocore.config import Config
from botocore.exceptions import ClientError


def main():
    try:
        credentials = json.loads(Path('/run/secrets/s3_admin').read_text())
        client = boto3.client('s3', endpoint_url='http://s3:8333', region_name=os.environ['S3_REGION'],
                              aws_access_key_id=credentials['access_key'], aws_secret_access_key=credentials['secret_key'],
                              config=Config(connect_timeout=2, read_timeout=2, retries={'max_attempts': 0}, s3={'addressing_style': 'path'}))
        deadline = time.monotonic() + 120
        while True:
            try:
                client.list_buckets()
                break
            except Exception:
                if time.monotonic() >= deadline:
                    raise RuntimeError('storage unavailable')
                time.sleep(2)
        bucket = os.environ['S3_BUCKET']
        try:
            client.head_bucket(Bucket=bucket)
        except ClientError as exc:
            if exc.response['ResponseMetadata']['HTTPStatusCode'] != 404:
                raise
            client.create_bucket(Bucket=bucket, ACL='private')
        print('private_bucket_ready')
        return 0
    except Exception:
        print('s3_bootstrap_failed: check configuration and storage')
        return 1


if __name__ == '__main__':
    sys.exit(main())
