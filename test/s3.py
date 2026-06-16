from djevops.s3 import get_client

def delete_directory_from_s3(config, prefix):
    client = get_client(config)
    bucket = config['bucket']
    paginator = client.get_paginator('list_objects_v2')
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        objects = [{'Key': obj['Key']} for obj in page.get('Contents', [])]
        client.delete_objects(Bucket=bucket, Delete={'Objects': objects})
