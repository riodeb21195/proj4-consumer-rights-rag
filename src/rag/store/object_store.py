"""Raw-document archive in S3-compatible object storage (MinIO locally)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import boto3
from botocore.exceptions import ClientError

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client

log = logging.getLogger(__name__)


def raw_key(slug: str, builddate: str, sha256: str) -> str:
    """Content-addressed key: the same XML always lands at the same key (idempotent uploads)."""
    return f"{slug}/{builddate}_{sha256[:16]}.xml"


class RawStore:
    def __init__(self, client: S3Client, bucket: str) -> None:
        self.client = client
        self.bucket = bucket

    @classmethod
    def from_settings(
        cls, endpoint_url: str, access_key: str, secret_key: str, bucket: str
    ) -> RawStore:
        client = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name="us-east-1",
        )
        return cls(client, bucket)

    def ensure_bucket(self) -> None:
        try:
            self.client.head_bucket(Bucket=self.bucket)
        except ClientError:
            self.client.create_bucket(Bucket=self.bucket)
            log.info("created bucket", extra={"bucket": self.bucket})

    def exists(self, key: str) -> bool:
        try:
            self.client.head_object(Bucket=self.bucket, Key=key)
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in {"404", "NoSuchKey", "NotFound"}:
                return False
            raise
        return True

    def put_if_absent(self, key: str, data: bytes, metadata: dict[str, str]) -> bool:
        """Upload unless the key exists. Returns True if something was written."""
        if self.exists(key):
            return False
        self.client.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=data,
            ContentType="application/xml",
            Metadata=metadata,
        )
        return True

    def get(self, key: str) -> bytes:
        return self.client.get_object(Bucket=self.bucket, Key=key)["Body"].read()
