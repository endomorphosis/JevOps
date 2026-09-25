"""Small structural proof-term IR for constructive search, not a Lean parser."""
from __future__ import annotations

import re

NAME = r"[^\W\d][\w']*"
CONSTANTS = frozenset(("False.elim", "True.intro", "And.left", "And.right", "Or.inl", "Or.inr", "Or.elim"))


def node(op, *args, name=""):
    return {"op": op, "name": name, "args": list(args)}


def validate_tree(tree):
    """Bound the unfolded tree, including repeated/shared subtrees, before recursion."""
    pending, count = [(tree, 0)], 0
    arities = {"local": 0, "const": 0, "app": 2, "proj": 1, "lambda": 1, "pair": 2}
    while pending:
        current, depth = pending.pop()
        count += 1
        if count > 4096 or depth > 128:
            raise ValueError("constructive term IR budget")
        if (type(current) is not dict or set(current) != {"op", "name", "args"}
                or type(current["op"]) is not str or current["op"] not in arities
                or type(current["name"]) is not str or len(current["name"]) > 256 or type(current["args"]) is not list
                or len(current["args"]) != arities[current["op"]]):
            raise ValueError("strict constructive term IR required")
        op, name = current["op"], current["name"]
        if ((op in {"local", "lambda"} and not re.fullmatch(NAME, name))
                or (op == "const" and name not in CONSTANTS)
                or (op == "proj" and name not in {"left", "right", "mp", "mpr"})
                or (op in {"app", "pair"} and name)):
            raise ValueError("unsupported constructive term IR name")
        pending.extend((arg, depth + 1) for arg in current["args"])


def render_tree(tree, replacements=None):
    """Replace local leaves, never substrings. Replacements are trusted renderings.

    Each replacement is (text, atomic). Callers construct these from validated
    declarations/formulas, not source snippets. Lean still checks every draft.
    Bound-variable collisions fail closed instead of textual capture.
    """
    validate_tree(tree)
    replacements = dict(replacements or {})
    if len(replacements) > 16 or any(type(n) is not str or not re.fullmatch(NAME, n) or type(v) is not tuple or len(v) != 2
           or type(v[0]) is not str or not v[0] or len(v[0].encode()) > 65536 or type(v[1]) is not bool
           for n, v in replacements.items()):
        raise ValueError("bounded typed local replacements required")
    # Conservative capture check: identifiers in supplied expressions/formulas
    # may be free. Reject collisions even when a qualified name would be safe.
    replacement_identifiers = {n for text, _ in replacements.values() for n in re.findall(NAME, text)}

    def render(t):
        op, name, args = t["op"], t["name"], t["args"]
        if op == "local":
            return replacements.get(name, (name, True))
        if op == "const":
            return "_root_." + name, True
        if op == "lambda" and (name in replacements or name in replacement_identifiers):
            raise ValueError("replacement would cross a shadowing binder")
        children = [render(a) for a in args]
        def arg(i):
            text, atom = children[i]
            return text if atom else "(" + text + ")"
        if op == "app":
            # Left-associated applications need no redundant parentheses.
            left = children[0][0] if args[0]["op"] == "app" else arg(0)
            text, atom = left + " " + arg(1), False
        elif op == "proj":
            # A global declaration followed by .mp could resolve as a different
            # qualified name. Parenthesize substituted/global expressions.
            local = args[0]["op"] == "local" and args[0]["name"] not in replacements
            base = children[0][0] if local or args[0]["op"] == "proj" else "(" + children[0][0] + ")"
            text, atom = base + "." + name, True
        elif op == "lambda":
            text, atom = "fun " + name + " => " + children[0][0], False
        else:
            text, atom = "⟨" + children[0][0] + ", " + children[1][0] + "⟩", True
        if len(text.encode()) > 65536:
            raise ValueError("rendered constructive term byte budget")
        return text, atom
    return render(tree)[0]
