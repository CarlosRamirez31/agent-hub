"""Routing hints from recent native quota snapshots; no model calls or estimates."""
import json
import math
import re
import time
from pathlib import Path


def failure_reason(message):
    value = str(message).casefold()
    if re.search(r'quota|usage.limit|rate.limit|resource.exhausted|insufficient.(?:balance|credit)|credit.balance|limit.reached', value):
        return 'quota_exhausted'
    if re.search(r'token.limit|context.length|context.window', value):
        return 'token_limit'
    if re.search(r'provider.unavailable|service.unavailable|temporarily.unavailable', value):
        return 'provider_unavailable'
    return None


def quota(profile, state, now=None):
    now = time.time() if now is None else now
    ident = profile.get('adapter')
    if not ident or not re.fullmatch(r'[a-z][a-z0-9_-]{0,63}', ident) or state is None:
        return {'status': 'unknown', 'remaining': None}
    try:
        path = Path(state)/'usage-cache'/(ident+'.json')
        if path.stat().st_size > 65536:
            raise ValueError('oversized')
        data = json.loads(path.read_text())
        age = now-data['checked_at']
        if not 0 <= age <= 300:
            raise ValueError('stale')
        if data.get('provider') != profile['provider']:
            raise ValueError('different provider')
        buckets = {}
        for window in data['windows']:
            remaining, reset = window.get('remaining'), window.get('resets')
            if isinstance(remaining, bool) or not isinstance(remaining, (int, float)) or not math.isfinite(remaining) or not 0 <= remaining <= 100:
                continue
            if reset is not None and (isinstance(reset, bool) or not isinstance(reset, (int, float)) or not math.isfinite(reset) or reset <= now):
                continue
            # Antigravity publishes independent model groups. Without an exact
            # group mapping, only consider the whole provider low if every group is.
            group = str(window.get('label', '')).split(' · ')[0] if profile['provider'] == 'antigravity' else 'account'
            buckets.setdefault(group, []).append(remaining)
        remaining = max(min(values) for values in buckets.values()) if buckets else None
        status = 'unknown' if remaining is None else 'exhausted' if remaining == 0 else 'low' if remaining <= 10 else 'available'
        return {'status': status, 'remaining': remaining}
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return {'status': 'unknown', 'remaining': None}
