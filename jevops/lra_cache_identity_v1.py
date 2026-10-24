"""Environment-complete SHA256 cache identities for source and context."""

import hashlib
import json


def cache_key(context, source):
    """Return the SHA256 hex digest of the canonical cache record.

    The record is UTF-8 JSON for {"context": context, "source": source},
    with ensure_ascii false, sorted keys, and separators (",", ":").
    context and source are left unchanged. source is embedded exactly,
    with no normalization.
    """
    record = {"context": context, "source": source}
    canonical = json.dumps(
        record,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
