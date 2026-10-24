"""Length-first selection among already verified, axiom-preserving candidates.

This module does not verify Lean proofs, axioms, tokens, or heartbeats.
It only chooses among rows that already carry those independent results.
"""


def select_candidate(rows):
    """Return the admissible id minimizing (tokens, heartbeats, id), or None.

    A row is admissible only when it is a dict whose id is a str, whose
    tokens value is an int of at least 1, whose heartbeats value is an int
    of at least 0, and whose verified and axioms_preserved values are the
    literal True. Bool is not an int. Invalid rows are skipped. An empty
    input or no admissible row yields None. The input is not mutated.
    """
    best_key = None
    best_id = None
    try:
        candidates = iter(rows)
    except TypeError:
        return None
    for row in candidates:
        if type(row) is not dict:
            continue
        identifier = row.get("id")
        tokens = row.get("tokens")
        heartbeats = row.get("heartbeats")
        if type(identifier) is not str:
            continue
        if type(tokens) is not int or tokens < 1:
            continue
        if type(heartbeats) is not int or heartbeats < 0:
            continue
        if row.get("verified") is not True or row.get("axioms_preserved") is not True:
            continue
        key = (tokens, heartbeats, identifier)
        if best_key is None or key < best_key:
            best_key = key
            best_id = identifier
    return best_id
