from botocore.config import Config
from botocore.exceptions import ClientError

import boto3
import botocore

def upload(config, local_path, remote_path):
    client = get_client(config)
    client.upload_file(local_path, config['bucket'], remote_path)

def download(config, local_path, remote_path):
    client = get_client(config)
    try:
        client.download_file(config['bucket'], remote_path, local_path)
    except ClientError as e:
        if e.response['Error']['Code'] in ('404', 'NoSuchKey'):
            return False
        raise
    return True

def get_client(config):
    endpoint = config.get('endpoint')
    return boto3.client(
        's3',
        region_name=config.get('region'),
        endpoint_url=f'https://{endpoint}' if endpoint else None,
        aws_access_key_id=config['access-key-id'],
        aws_secret_access_key=config['secret-access-key'],
        config=_get_botocore_config(config)
    )

def _get_botocore_config(config):
    kwargs = {
        's3': {
            'addressing_style':
                'path' if config.get('force-path-style') else 'auto',
            'payload_signing_enabled': config.get('sign-payload', False),
        }
    }
    if _botocore_version() >= (1, 36):
        # boto3 >= 1.36 sends CRC32 integrity checksums by default, which
        # Ceph-based providers such as Linode reject with AccessDenied. The
        # options that disable this only exist from 1.36 on.
        kwargs['request_checksum_calculation'] = 'when_required'
        kwargs['response_checksum_validation'] = 'when_required'
    return Config(**kwargs)

def _botocore_version():
    return tuple(int(part) for part in botocore.__version__.split('.')[:2])
