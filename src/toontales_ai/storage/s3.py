"""S3-объекты приватны; клиент получает только short-lived presigned URL
(review.md §6, §8) — storage_key никогда не отдаётся как постоянный публичный URL."""

import boto3

from toontales_ai.config.settings import get_settings

_settings = get_settings()

_s3_client = boto3.client(
    "s3",
    endpoint_url=_settings.s3_endpoint_url,
    region_name=_settings.s3_region,
    aws_access_key_id=_settings.s3_access_key or None,
    aws_secret_access_key=_settings.s3_secret_key or None,
)

PRESIGNED_URL_TTL_SECONDS = 300


def presigned_get_url(storage_key: str, *, ttl_seconds: int = PRESIGNED_URL_TTL_SECONDS) -> str:
    return _s3_client.generate_presigned_url(
        "get_object",
        Params={"Bucket": _settings.s3_bucket, "Key": storage_key},
        ExpiresIn=ttl_seconds,
    )


def download_to_path(storage_key: str, destination) -> None:
    _s3_client.download_file(_settings.s3_bucket, storage_key, str(destination))


def upload_from_path(source_path, storage_key: str, *, content_type: str) -> None:
    _s3_client.upload_file(
        str(source_path), _settings.s3_bucket, storage_key, ExtraArgs={"ContentType": content_type}
    )
