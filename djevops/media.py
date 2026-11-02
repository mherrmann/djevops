from django.core.files.storage import default_storage, FileSystemStorage
from django.urls import Resolver404, get_script_prefix, resolve

_PROBE_FILE_NAME = 'djevops-probe'

def get_public_media_url():
    # Other storage backends, such as S3, do not store uploads on this server.
    if not isinstance(default_storage, FileSystemStorage):
        return None
    result = default_storage.base_url
    # This checks whether MEDIA_URL is set.
    if result == get_script_prefix():
        return None
    # A full URL means that another server is responsible for the uploads.
    if not result.startswith('/') or result.startswith('//'):
        return None
    # A Django view at this URL may enforce access control, which Nginx must not
    # bypass.
    try:
        resolve(result + _PROBE_FILE_NAME)
    except Resolver404:
        # MEDIA_URL is empty unless the developer sets it, and means "this is
        # where MEDIA_ROOT is served". We therefore take it as the decision to
        # make uploads public.
        return result
    return None
