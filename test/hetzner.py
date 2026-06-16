from hcloud import Client as HetznerClient
from hcloud._exceptions import APIException
from hcloud.images import Image
from hcloud.server_types import ServerType

def create_server(
    api_token, ssh_key, name, server_type='cx23', image='debian-13'
):
    client = HetznerClient(token=api_token)
    response = client.servers.create(
        name=name, server_type=ServerType(name=server_type),
        image=Image(name=image), ssh_keys=[ssh_key]
    )
    return response.server

def ensure_ssh_key_exists(api_token, ssh_key_content, name):
    client = HetznerClient(token=api_token)
    try:
        return client.ssh_keys.create(name=name, public_key=ssh_key_content)
    except APIException as e:
        if e.code != 'uniqueness_error':
            raise
        all_keys = client.ssh_keys.get_all()
        for key in all_keys:
            if key.public_key == ssh_key_content:
                return key
        else:
            raise LookupError("SSH key exists but couldn't find it via the API")
