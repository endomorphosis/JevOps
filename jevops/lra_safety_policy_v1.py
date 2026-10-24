"""Fail-closed filter for trusted verifier summaries.

This module never proves Lean and never reads or writes proof artifacts.
It only accepts a summary row when the trusted verifier already recorded
exact preservation and pin results and rejected sorry or unsafe claims.
"""


def accept_candidate(row):
    """Return True only for an unmodified dict with exact Boolean verifier flags.

    statement_preserved, type_preserved, all_pins_verified, and axioms_subset
    must each be the literal True. has_sorry and unsafe must each be the
    literal False. A non-dict, a missing field, or any other value returns
    False. The row is only read.
    """
    if type(row) is not dict:
        return False
    if row.get("statement_preserved") is not True:
        return False
    if row.get("type_preserved") is not True:
        return False
    if row.get("all_pins_verified") is not True:
        return False
    if row.get("axioms_subset") is not True:
        return False
    if row.get("has_sorry") is not False:
        return False
    if row.get("unsafe") is not False:
        return False
    return True
