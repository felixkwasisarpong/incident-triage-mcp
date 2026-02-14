from __future__ import annotations
import os
import json
import boto3
from typing import Any, Dict

def read_evidence_bundle(incident_id: str) -> Dict[str, Any]:
    bucket = os.getenv("S3_BUCKET", "triage-artifacts")
    key = f"evidence/v1/{incident_id}.json"

    s3 = boto3.client(
        "s3",
        endpoint_url=os.getenv("S3_ENDPOINT_URL"),
        region_name=os.getenv("S3_REGION", "us-east-1"),
        aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
    )

    try:
        obj = s3.get_object(Bucket=bucket, Key=key)
    except s3.exceptions.NoSuchKey:
        return {"found": False, "uri": f"s3://{bucket}/{key}"}

    raw = obj["Body"].read().decode("utf-8")
    return {"found": True, "uri": f"s3://{bucket}/{key}", "raw": json.loads(raw)}