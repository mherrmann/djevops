# We forbid sniffing and sandbox uploaded files because they are untrusted: An
# uploaded HTML or SVG file could run scripts with access to the site's origin.
# This does not affect embedding the files, eg. via <img>.
_MEDIA_LOCATION = """location $URL {
        alias $ROOT;
        autoindex off;
        add_header X-Content-Type-Options nosniff;
        add_header Content-Security-Policy "$CSP";
    }"""
_MEDIA_CSP = "default-src 'none'; style-src 'unsafe-inline'; sandbox"

def get_header_name_from_meta_key(meta_key):
    if not meta_key.startswith('HTTP_'):
        raise ValueError(f'Invalid meta key: {meta_key!r}')
    meta_key = meta_key[len('HTTP_'):]
    return meta_key.replace('_', '-').title()

def get_nginx_size_from_bytes(num_bytes):
    # A value of None means "no limit" in Django; `0` means the same in Nginx.
    if num_bytes is None:
        return '0'
    for unit, factor in (('G', 2 ** 30), ('M', 2 ** 20), ('K', 2 ** 10)):
        if num_bytes and num_bytes % factor == 0:
            return f'{num_bytes // factor}{unit}'
    return str(num_bytes)

def get_media_location(url, root):
    # Both paths must end in a slash. Otherwise, `alias` allows path traversal.
    assert url.endswith('/'), url
    return _MEDIA_LOCATION \
        .replace('$URL', url) \
        .replace('$ROOT', root + '/') \
        .replace('$CSP', _MEDIA_CSP)
