"""Custom S3 storage backend that uses IAM role credentials only.

Skips AWS environment variables (AWS_ACCESS_KEY_ID, etc.) so that the
instance IAM role is used for S3, even when env vars are set for other
AWS services (e.g. Bedrock).
"""

import boto3
import botocore.session
from storages.backends.s3boto3 import S3Boto3Storage


class IAMRoleS3Storage(S3Boto3Storage):
    def _create_session(self):
        bc_session = botocore.session.Session()
        bc_session.get_component("credential_provider").remove("env")
        return boto3.Session(botocore_session=bc_session)
