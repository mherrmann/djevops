import re

def parse_sync_interval(sync_interval):
    error = ValueError(f'Invalid sync interval: {sync_interval!r}')
    m = re.match(r'^(\d+)(s|m|h)$', sync_interval)
    if not m:
        raise error
    num = int(m.group(1))
    unit = m.group(2)
    try:
        multiplier = {
            's': 1,
            'm': 60,
            'h': 3600,
        }[unit]
    except KeyError:
        raise error from None
    if num <= 0:
        raise error
    return num * multiplier

def as_cron(interval_secs):
    if interval_secs % 60:
        raise ValueError(
            f'A sync interval of {interval_secs}s is not a whole number of '
            f'minutes.'
        )
    minutes = interval_secs // 60
    if minutes < 60:
        return f'*/{minutes} * * * *'
    if minutes == 24 * 60:
        return '0 0 * * *'
    hours, remainder = divmod(minutes, 60)
    if remainder == 0 and hours < 24:
        return f'0 */{hours} * * *'
    raise ValueError(
        f'A sync interval of {interval_secs}s cannot be expressed as a cron '
        f'schedule. Use a whole number of minutes below 60, a whole number of '
        f'hours below 24, or 24h.'
    )
