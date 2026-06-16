from botocore.config import Config

import boto3

def delete_directory_from_s3(
    region, endpoint, access_key, secret_key, bucket, prefix
):
    client = _get_client(region, endpoint, access_key, secret_key)
    paginator = client.get_paginator('list_objects_v2')
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        objects = [{'Key': obj['Key']} for obj in page.get('Contents', [])]
        client.delete_objects(Bucket=bucket, Delete={'Objects': objects})

def _get_client(region, endpoint, access_key, secret_key):
    config = Config(s3={
        'addressing_style': 'path',
        'payload_signing_enabled': True
    })
    return boto3.client(
        's3',
        region_name=region,
        endpoint_url='https://' + endpoint,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        config=config
    )
