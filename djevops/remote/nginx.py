def get_header_name_from_meta_key(meta_key):
    if not meta_key.startswith('HTTP_'):
        raise ValueError(f'Invalid meta key: {meta_key!r}')
    meta_key = meta_key[len('HTTP_'):]
    return meta_key.replace('_', '-').title()
