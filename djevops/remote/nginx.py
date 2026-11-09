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

def get_django_locations(body_limits, service_name):
    # nginx picks the longest matching prefix, so the order of the locations
    # does not matter. Put / last for readability.
    prefixes = sorted(set(body_limits) - {'/'}) + ['/']
    result = []
    for prefix in prefixes:
        directives = [
            get_client_max_body_size(body_limits, prefix),
            f'include /etc/nginx/includes/{service_name}-django;'
        ]
        body = '\n        '.join(d for d in directives if d)
        result.append(f'location {prefix} {{\n        {body}\n    }}')
    return '\n\n    '.join(result)

def get_client_max_body_size(body_limits, prefix):
    size = body_limits.get(prefix)
    return f'client_max_body_size {size};' if size else ''

def get_media_location(url, root):
    # Both paths must end in a slash. Otherwise, `alias` allows path traversal.
    assert url.endswith('/'), url
    return _MEDIA_LOCATION \
        .replace('$URL', url) \
        .replace('$ROOT', root + '/') \
        .replace('$CSP', _MEDIA_CSP)
