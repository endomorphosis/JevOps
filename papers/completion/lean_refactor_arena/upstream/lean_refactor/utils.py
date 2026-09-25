import re
from importlib.machinery import SourceFileLoader
from pathlib import Path

from easydict import EasyDict as AttrDict

DEFAULT_IMPORTS = (
    "import Mathlib\nimport Aesop\n\nset_option maxHeartbeats 0\n\nopen BigOperators Real Nat Topology Rat\n\n"
)


def is_tactic_style_proof(proof: str) -> bool:
    """
    Check whether a Lean 4 proof uses tactic-mode style.

    A tactic-mode proof has its body starting with `:= by` (with possible
    whitespace/newlines between `:=` and `by`).  Term-mode proofs use `:=`
    followed by an expression that is NOT `by`.

    This function first uses `return_theorem_to_prove_mathlib_style` to locate
    the `:=` that ends the signature, then checks whether the token immediately
    after `:=` (ignoring whitespace) is `by`.

    Args:
        proof: The full Lean 4 theorem source (signature + proof body).

    Returns:
        True if the proof body starts with `:= by`, False otherwise.
    """
    if not proof:
        return False

    # Clean up: remove leading comments/attributes
    cleaned = remove_initial_comments_and_attr(proof)
    cleaned = remove_comments(cleaned)

    # Find the signature span ending at `:=`
    span = return_theorem_to_prove_mathlib_style(cleaned)
    if span is None:
        return False

    _, sig_end = span

    # The text after `:=` — skip whitespace and check for `by`
    rest = cleaned[sig_end:].lstrip()

    # Match `by` as a whole word
    return bool(re.match(r"by\b", rest))


def extract_doc_string(code: str) -> str | None:
    """
    Extract the doc string from the beginning of a Lean 4 code string.

    Doc strings in Lean 4 are written as /-- ... -/ and must appear at the
    beginning of the string (possibly with leading whitespace).

    Args:
        code: The Lean 4 source code string

    Returns:
        The doc string content (without /-- and -/ markers), or None if no doc string found.
    """
    if not code:
        return None

    _, code = extract_and_remove_attributes(code)

    # Skip leading whitespace
    stripped = code.lstrip()

    # Check if it starts with /--
    if not stripped.startswith("/--"):
        return None

    # Find the closing -/
    # Start searching after /--
    start_idx = 3  # len('/--')
    end_idx = stripped.find("-/", start_idx)

    if end_idx == -1:
        # No closing -/ found
        return None

    # Extract the content between /-- and -/
    doc_content = stripped[start_idx:end_idx]

    return doc_content.strip()


def extract_and_remove_attributes(text: str):
    """
    Extract a leading block of attribute(s) like:

        @[simp]
        @[aesop unsafe 10% (rule_sets := [Matroid])]
        @[to_additive
          "A technical lemma ... [Halmos, §60 Th. A] ..."]

    and return (attr_block, cleaned_text).

    - Handles nested brackets `[Measurable]`, `[Matroid]`, `[Halmos, ...]`, etc.
    - Stops *exactly* at the matching ']' for each `@[ ... ]`.
    - Does NOT eat into the lemma/proof, even if they contain `]` later.
    """
    n = len(text)
    if n == 0:
        return "", text

    # Allow leading whitespace before the first attribute
    pos = 0
    while pos < n and text[pos].isspace():
        pos += 1

    # If the first non-whitespace thing isn't '@[', no attribute block
    if not (pos + 1 < n and text[pos] == "@" and text[pos + 1] == "["):
        return "", text

    attr_block_start = 0
    attr_block_end = attr_block_start

    cur = pos
    first_attr_start = pos

    while cur < n and text[cur] == "@" and cur + 1 < n and text[cur + 1] == "[":
        attr_end = _parse_single_attribute(text, cur)
        if attr_end is None:
            # If malformed, bail out and don't strip anything
            return "", text

        # Attribute ends right after its matching ']'
        attr_block_end = attr_end

        # Skip whitespace (including newlines) after this attribute
        # but stop at the first non-whitespace character (lemma/def/etc.)
        while attr_block_end < n and text[attr_block_end].isspace():
            attr_block_end += 1

        # See if there is another attribute immediately after
        cur = attr_block_end
        if not (cur + 1 < n and text[cur] == "@" and text[cur + 1] == "["):
            break

    # Sanity: if we never advanced past the first attribute start, do nothing
    if attr_block_end <= first_attr_start:
        return "", text

    # Include any leading whitespace before the first attribute in the block
    attr_block = text[attr_block_start:attr_block_end]
    cleaned_text = text[attr_block_end:]

    return attr_block, cleaned_text


def remove_initial_comments_and_attr(code: str) -> str:
    """
    Removes initial comments (both single-line '--' and block '/- ... -/')
    from the beginning of a Lean 4 code string using regex.

    Note: This regex approach does NOT correctly handle nested block comments
    (e.g. '/- ... /- ... -/ ... -/'). It will stop at the first '-/'.
    """
    # Pattern breakdown:
    # 1. \s+        : One or more whitespace characters (spaces, tabs, newlines)
    # 2. --[^\n]* : Single-line comment: '--' followed by anything that isn't a newline
    # 3. /-.*?-/    : Block comment: '/-' followed by anything (non-greedy) until '-/'
    #
    # We combine these alternatives | in a non-capturing group (?:...)
    # and match one or more sequences (+) at the start of the string.
    # re.DOTALL is essential so that '.' in block comments matches newlines.
    if not code:
        print("received empty code in remove_initial_comments_and_attr", flush=True)
        return code

    pattern = r"^(?:\s+|--[^\n]*|/-.*?-/)+"

    match = re.match(pattern, code, re.DOTALL)

    if match:
        cleaned_code = code[match.end() :]
    else:
        cleaned_code = code

    _, cleaned_code = extract_and_remove_attributes(cleaned_code)
    return cleaned_code


def create_initial_gen_prompt_competition_math_goedel(formal_statement, imports, special_ending_prompt=""):
    prompt = f"Complete the following Lean 4 code:\n\n```lean4\n{imports}{formal_statement}```\n\nBefore producing the Lean 4 code to formally prove the given theorem, provide a detailed proof plan outlining the main proof steps and strategies.\nThe plan should highlight key ideas, intermediate lemmas, and proof structures that will guide the construction of the final formal proof."
    prompt += special_ending_prompt
    return prompt


def create_initial_gen_prompt_competition_math(formal_statement, imports, special_ending_prompt=""):
    prompt = f"Complete the following Lean 4 code:\n\n```lean4\n{imports}{formal_statement}```\n\nBefore producing the Lean 4 code to formally prove the given theorem, provide a detailed proof plan outlining the main proof steps and strategies.\nThe plan should highlight key ideas, intermediate lemmas, and proof structures that will guide the construction of the final formal proof. After you provide the proof plan, you must provide the completed full Lean 4 code (the original theorem declaration and the completed proof) at the end wrapped by ```lean4 ...``` tag."
    prompt += special_ending_prompt
    return prompt


def generate_correction_prompt(
    history_messages_from_prev_round,
    prev_round_llm_raw_output,
    error_message_from_prev_round,
    current_correction_round_num,
):
    prev_messages = list(history_messages_from_prev_round)

    prev_messages.append({"role": "assistant", "content": prev_round_llm_raw_output})

    cur_prompt = (
        f"The proof (Round {current_correction_round_num - 1}) is not correct. Following is the compilation error message, where we use <error></error> to signal the position of the error.\n\n{error_message_from_prev_round}"
        "\n\nBefore producing the Lean 4 code that fixes the error, provide a detailed analysis of the error message."
    )
    return cur_prompt, prev_messages


def create_initial_gen_prompt(
    task_type, original_lean4_code, full_name, file_path, dependencies, signature, informalization
):
    if task_type == "simplify":
        return ""
    elif task_type == "complexify":
        init_prompt = """You are an expert in Lean 4 and Mathlib 4. Your task is to make an existing Lean 4 proof for a theorem sourced from Mathlib4 more complex, while ensuring the complexified proof is still correct.
**Instructions:**
1. Invariant Signature: Your output proof must reproduce the theorem declaration (name, parameters, type) exactly as provided. Do not modify the theorem statement in any way.
2. Complexify the Proof: Rewrite the proof body to be more logically and structurally complex, or more verbose. But you should avoid trivial no-ops; the added complexity should look like a "detailed manual derivation" rather than garbage code.
3. Correctness: Ensure that your output complexified proof will verify correctly in Lean 4 when pasted into the source file. You must not use "sorry" in your proof.
4. Formatting: Output the entire theorem (signature + new proof) inside a lean4 tagged code block, ensuring the content is ready to run immediately when pasted into the source file.

You will now be given the original proof for the theorem, the theorem’s elaborated signature, the informal description, and the dependent Lean statements that the original proof uses.

**Inputs:**

Original proof:
```lean4
{statement}
```
Theorem's full name: {full_name}

Theorem's elaborated signature: {signature}

Theorem's informal description: {informal_description}

Information about the dependencies used in the original proof:
{dependencies}

Now, provide your complexified proof.
"""
        contexts = []
        for dep in dependencies:
            if dep["classification"] not in ["class", "structure"]:
                contexts.append({
                    "full name": dep["full_name"],
                    "informal description": dep["informal_description"],
                    "elaborated signature": dep["detailed_info"],
                })
            else:
                contexts.append({
                    "full name": dep["full_name"],
                    "informal description": dep["informal_description"],
                    "class/structure detailed information": dep["detailed_info"],
                })
        prompt = init_prompt.format(
            statement=original_lean4_code,
            full_name=full_name,
            signature=signature,
            informal_description=informalization,
            dependencies=contexts,
        )
        return prompt
    else:
        raise ValueError(f"Invalid task type: {task_type}")


def return_theorem_to_prove_goedel_style(text):
    # Pattern that matches from 'theorem' or 'lemma' to ':= by sorry' with any content in between
    pattern = r"((?:theorem).*?:=\s*by\s*sorry)"
    match = re.search(pattern, text, re.DOTALL)
    return match.span() if match else None


def return_theorem_to_replace_goedel_style(text):
    # Pattern that matches from 'theorem' or 'lemma' to ':= by sorry' with any content in between
    pattern = r"((?:^|\s)theorem\s+.*?:=\s*by)"
    match = re.search(pattern, text, re.DOTALL)
    return match.span() if match else None


def return_theorem_to_replace_mathlib_style(text):
    return return_theorem_to_prove_mathlib_style(text)


def return_theorem_to_prove_mathlib_style(text):
    """
    Extracts the signature of a Mathlib theorem/lemma.

    Logic:
    1. Finds the start of the theorem (modifiers + keyword).
    2. Scans forward character by character to find the assignment `:=`.
    3. Ignores `:=` found inside (), [], or {}.
    4. If `:=` is found at depth 0, returns the signature ending there.
    5. If `:=` is NOT found, falls back to the original regex to find a signature ending in `|`.
    """

    MODIFIERS = {"private", "protected", "noncomputable", "nonrec", "unsafe", "partial", "scoped", "local"}

    mods_pattern = "|".join(MODIFIERS)

    # 1. FIND THE START (for scanning :=)
    # matches: modifiers (optional) + whitespace + theorem/lemma
    start_pattern = (
        r"\s*"
        r"(?:(?:" + mods_pattern + r")\s+)*"
        r"\s*"
        r"(?:theorem|lemma)\b"  # \b ensures we don't match "theorems" inside a word
    )

    # We use search to find the start index in the text
    start_match = re.search(start_pattern, text, re.DOTALL)

    if start_match:
        start_index = start_match.start()
        current_index = start_match.end()

        # 2. SCAN FOR := WITH BRACKET AWARENESS
        bracket_stack = []
        # Map closer to opener
        brackets_map = {")": "(", "]": "[", "}": "{"}
        open_brackets = set(brackets_map.values())
        close_brackets = set(brackets_map.keys())

        text_len = len(text)

        while current_index < text_len:
            char = text[current_index]

            # Check if we are at Depth 0 (not inside any brackets)
            if len(bracket_stack) == 0:
                # Check for ":=" safely
                # Ensure we have at least 2 chars remaining including current
                if current_index + 1 < text_len:
                    if text[current_index : current_index + 2] == ":=":
                        # Found the assignment. Return span ending after ":="
                        return (start_index, current_index + 2)

            # Handle Nesting
            if char in open_brackets:
                bracket_stack.append(char)
            elif char in close_brackets:
                # If stack is not empty and matches top
                if bracket_stack and bracket_stack[-1] == brackets_map[char]:
                    bracket_stack.pop()
                # Note: We ignore unbalanced closing brackets to be robust

            current_index += 1

    # 3. FALLBACK: ORIGINAL REGEX FOR "|"
    # If we are here, either we didn't find 'theorem' (unlikely if text is valid)
    # OR we scanned the whole text and didn't find a top-level ":=".
    # We now try the pattern matching style regex.

    prefix = (
        r"\s*"
        r"(?:(?:" + mods_pattern + r")\s+)*"
        r"\s*"
        r"(?:theorem|lemma)"
        r".*?"
    )

    # Matches: [prefix] [optional space] |
    pattern_match = r"(" + prefix + r"\s*\|)"
    match = re.search(pattern_match, text, re.DOTALL)
    if match:
        return match.span()

    return None


def replace_statement_in_proof_mathlib_style(statement, proof):  # original, extracted
    if ("apply?" in proof) or ("exact?" in proof):
        return "**Error**, 'apply?' or 'exact?' is used, which is not allowed."
    stats_re = statement
    stats_span_ = return_theorem_to_prove_mathlib_style(stats_re)
    if stats_span_ is None:
        error_app = "\n".join(["\n"] + ["-- " + x for x in statement.split("\n")])
        return f"**Error**, can not find the theorem/lemma declaration in {error_app}"
    proof_str = remove_comments(proof)
    span = return_theorem_to_replace_mathlib_style(proof_str)
    if span is None:
        error_app = "\n".join(["\n"] + ["-- " + x for x in proof.split("\n")])
        return f"**Error**, can not find the theorem/lemma declaration in {error_app}"
    return stats_re[: stats_span_[1]] + proof_str[span[1] :]


def replace_statement_in_proof_goedel_style(statement, proof):  # original, extracted
    if ("apply?" in proof) or ("exact?" in proof):
        return "**Error**, 'apply?' or 'exact?' is used, which is not allowed."
    stats_re = remove_comments(statement)
    stats_span_ = return_theorem_to_replace_goedel_style(stats_re)
    if stats_span_ is None:
        error_app = "\n".join(["\n"] + ["-- " + x for x in statement.split("\n")])
        return f"**Error**, can not find the theorem/lemma declaration in {error_app}"
    proof_str = remove_comments(proof)
    span = return_theorem_to_replace_goedel_style(proof_str)
    if span is None:
        error_app = "\n".join(["\n"] + ["-- " + x for x in proof.split("\n")])
        return f"**Error**, can not find the theorem/lemma declaration in {error_app}"
    return stats_re[: stats_span_[1]].replace("sorry", "") + proof_str[span[1] :]


def get_error_str_goedel_style(code, errors, error_thres=True):
    err_str = ""
    code_lines = code.split("\n")
    token_lengths = [len(line) + 1 for line in code_lines]
    error_num_thres = 1 if error_thres else len(errors)

    for i, error in enumerate(errors[:error_num_thres]):
        start_line = error["pos"]["line"] - 1
        start_col = error["pos"]["column"]

        if error["endPos"] is None:
            end_line = start_line
            end_col = len(code_lines[start_line])
        else:
            end_line = error["endPos"]["line"] - 1
            end_col = error["endPos"]["column"]

        start_char_pos = sum(token_lengths[:start_line]) + start_col
        end_char_pos = sum(token_lengths[:end_line]) + end_col

        err_str += f"\nError {i + 1}:\n"
        err_str += "\nCorresponding Code:\n```lean4\n"

        error_code = ""
        for ii in range(-4, 0):
            if start_line + ii >= 0:
                error_code += f"{code_lines[start_line + ii]}\n"
        if start_line != end_line:
            error_code += code_lines[start_line][:start_col] + "<error>" + code_lines[start_line][start_col:] + "\n"

            if not error_thres:
                for j in range(start_line + 1, end_line):
                    error_code += f"{code_lines[j]}\n"
            else:
                show_line = 6
                for j in range(start_line + 1, min(end_line, start_line + show_line)):
                    error_code += f"{code_lines[j]}\n"
                if end_line > start_line + show_line:
                    leading_spaces = len(code_lines[j]) - len(code_lines[j].lstrip(" "))
                    error_code += "\n" + " " * leading_spaces + "... --[Truncated]-- ...\n"

            error_code += code_lines[end_line][:end_col] + "</error>" + code_lines[end_line][end_col:] + "\n"
        else:
            error_code += (
                code_lines[start_line][:start_col]
                + "<error>"
                + code_lines[start_line][start_col:end_col]
                + "</error>"
                + code_lines[start_line][end_col:]
                + "\n"
            )
        if end_line + 1 < len(code_lines):
            error_code += f"{code_lines[end_line + 1]}\n"

        err_str += error_code
        err_str += "\n```\n"
        err_str += f"\nError Message: {error['data']}\n"

    if len(errors) > error_num_thres:
        err_str += f"\n... [Omitted {len(errors) - error_num_thres} more errors] ...\n"

    return err_str


def get_error_str_from_lean_client(code, errors, error_thres=True):
    err_str = ""
    code_lines = code.split("\n")
    token_lengths = [len(line) + 1 for line in code_lines]
    error_num_thres = 1 if error_thres else len(errors)

    for i, error in enumerate(errors[:error_num_thres]):
        if error["severity"] != 1:
            continue
        start_line = error["range"]["start"]["line"]  # - 1
        start_col = error["range"]["start"]["character"]

        if error["range"]["end"] is None:
            end_line = start_line
            end_col = len(code_lines[start_line])
        else:
            end_line = error["range"]["end"]["line"]  # - 1
            end_col = error["range"]["end"]["character"]

        start_char_pos = sum(token_lengths[:start_line]) + start_col
        end_char_pos = sum(token_lengths[:end_line]) + end_col

        err_str += f"\nError {i + 1}:\n"
        err_str += "\nCorresponding Code:\n```lean4\n"

        error_code = ""
        for ii in range(-1, 0):  # number of lines shown before the error line
            if start_line + ii >= 0:
                error_code += f"{code_lines[start_line + ii]}\n"
        if start_line != end_line:
            error_code += code_lines[start_line][:start_col] + "<error>" + code_lines[start_line][start_col:] + "\n"

            if not error_thres:
                for j in range(start_line + 1, end_line):
                    error_code += f"{code_lines[j]}\n"
            else:
                show_line = 6
                for j in range(start_line + 1, min(end_line, start_line + show_line)):
                    error_code += f"{code_lines[j]}\n"
                if end_line > start_line + show_line:
                    leading_spaces = len(code_lines[j]) - len(code_lines[j].lstrip(" "))
                    error_code += "\n" + " " * leading_spaces + "... --[Truncated]-- ...\n"

            error_code += code_lines[end_line][:end_col] + "</error>" + code_lines[end_line][end_col:] + "\n"
        else:
            error_code += (
                code_lines[start_line][:start_col]
                + "<error>"
                + code_lines[start_line][start_col:end_col]
                + "</error>"
                + code_lines[start_line][end_col:]
                + "\n"
            )
        if end_line + 1 < len(code_lines):
            error_code += f"{code_lines[end_line + 1]}\n"

        err_str += error_code
        err_str += "\n```\n"
        err_str += f"\nError Message: {error['message']}\n"

    if len(errors) > error_num_thres:
        err_str += f"\n... [Omitted {len(errors) - error_num_thres} more errors] ...\n"

    return err_str


def post_process_output(out, original_statement, style="mathlib"):
    result = []
    for llm_output in out:
        if llm_output == "PROMPT TOO LONG":
            result.append(None)
            continue
        # print(f"llm output: {llm_output}", flush=True)
        extracted_code = extract_code(llm_output)
        # print(f"extracted code: {extracted_code}", flush=True)
        if style == "mathlib":
            replaced_code = replace_statement_in_proof_mathlib_style(original_statement, extracted_code)
        elif style == "competition":
            replaced_code = replace_statement_in_proof_goedel_style(original_statement, extracted_code)
        else:
            raise ValueError(f"Invalid style: {style}")
        # print(f"post processed code: {replaced_code}", flush=True)
        result.append(replaced_code)
    return result


def remove_comments(text):  # remove comments
    # First remove all /- ... -/ blocks
    text = re.sub(r"/-.*?-/", "", text, flags=re.DOTALL)
    # Then remove -- comments from each line
    lines = text.split("\n")
    cleaned_lines = []
    for line in lines:
        # Split on -- and keep only the first part
        cleaned_line = line.split("--", 1)[0]
        if cleaned_line.strip() == "":
            continue
        cleaned_lines.append(cleaned_line)
    # Join back together and remove excessive empty lines
    cleaned_text = "\n".join(cleaned_lines)
    return cleaned_text.strip()


def extract_code(inputs):
    pattern = r"```lean4\n(.*?)\n```"
    matches = re.findall(pattern, inputs, re.DOTALL)
    if matches:
        return matches[-1]
    pattern = r"```lean4\n(.*?)```"
    matches = re.findall(pattern, inputs, re.DOTALL)
    if matches:
        return matches[-1]
    pattern = r"```lean4(.*?)\n```"
    matches = re.findall(pattern, inputs, re.DOTALL)
    if matches:
        return matches[-1]
    pattern = r"```lean4(.*?)```"
    matches = re.findall(pattern, inputs, re.DOTALL)
    if matches:
        return matches[-1]
    pattern = r"```lean\n(.*?)\n```"
    matches = re.findall(pattern, inputs, re.DOTALL)
    if matches:
        return matches[-1]
    pattern = r"```lean\n(.*?)```"
    matches = re.findall(pattern, inputs, re.DOTALL)
    if matches:
        return matches[-1]
    pattern = r"```lean(.*?)\n```"
    matches = re.findall(pattern, inputs, re.DOTALL)
    if matches:
        return matches[-1]
    pattern = r"```lean(.*?)```"
    matches = re.findall(pattern, inputs, re.DOTALL)
    if matches:
        return matches[-1]
    return "None"


def _parse_single_attribute(text: str, start: int) -> int | None:
    """
    Given text and an index `start` where text[start:start+2] == '@[',
    return the index just *after* the matching closing ']' for this attribute.

    Uses bracket depth over '[' and ']'. Returns None if we hit EOF
    before closing.
    """
    n = len(text)
    assert text[start] == "@" and start + 1 < n and text[start + 1] == "["

    i = start + 2  # position after the initial '['
    depth = 1

    while i < n:
        c = text[i]
        if c == "[":
            depth += 1
        elif c == "]":
            depth -= 1
            if depth == 0:
                # i is the index of the closing ']', return position after it
                return i + 1
        i += 1

    # Unbalanced attribute: treat as invalid
    return None


def proof_length(statement_and_proof):
    """
    Compute the token count of a proof from a full statement string.
    Extracts the proof by finding where the signature ends, then tokenizes and counts.
    """
    lean_operators = [
        ":=",
        "!=",
        "&&",
        "-.",
        "->",
        "←",
        "..",
        "...",
        "::",
        ":>",
        "<;>",
        ";;",
        "==",
        "||",
        "=>",
        "<=",
        ">=",
        "⁻¹",
        "?_",
    ]
    lean_operators_spaced = [" ".join(conn) for conn in lean_operators]
    lean_operators_dict = dict(zip(lean_operators_spaced, lean_operators, strict=False))

    def lexer(lean_snippet):
        tokenized_lines = []
        for line in lean_snippet.splitlines():
            tokens = []
            token = ""
            for ch in line:
                if ch == " ":
                    if token:
                        tokens.append(token)
                        token = ""
                elif str.isalnum(ch) or (ch in "._'"):
                    token += ch
                else:
                    if token:
                        tokens.append(token)
                        token = ""
                    tokens.append(ch)
            if token:
                tokens.append(token)
            tokenized_line = " ".join(tokens)
            for conn in lean_operators_spaced:
                if conn in tokenized_line:
                    tokenized_line = tokenized_line.replace(conn, lean_operators_dict[conn])
            tokenized_lines.append(tokenized_line)
        return "\n".join(tokenized_lines)

    try:
        statement_and_proof = remove_comments(statement_and_proof)
        _, statement_and_proof = extract_and_remove_attributes(statement_and_proof)
        decl_start, decl_end = return_theorem_to_prove_mathlib_style(statement_and_proof)
        proof = statement_and_proof[decl_end:]
        proof_tokenized = lexer(proof)
        return sum([len(l.split(" ")) for l in proof_tokenized.splitlines()])
    except:
        return 10**9


def load_config(fname):
    name = Path(fname).stem
    mod = SourceFileLoader(name, fname).load_module()

    config = {}
    for n in dir(mod):
        if not n.startswith("__"):
            config[n] = getattr(mod, n)
    config = AttrDict(config)
    return config
