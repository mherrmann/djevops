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
