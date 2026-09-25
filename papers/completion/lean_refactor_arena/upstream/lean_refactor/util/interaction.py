import logging
import os
import time
from pathlib import Path
from typing import Any

import leanclient as lc


class LeanInteractor:
    """
    A class for interacting with Lean files and getting Lean server feedback.
    Can be instantiated multiple times for parallel processing.
    """

    def __init__(self, project_path: str, log_level: int = logging.DEBUG):
        """
        Initialize the Lean interactor.

        Args:
            project_path: Path to the Lean project root (where lakefile.toml is located)
            log_level: Logging level for leanclient (default: WARNING)
        """
        self.project_path = Path(project_path)
        logging.getLogger("leanclient").setLevel(log_level)
        self.client = lc.LeanLSPClient(str(self.project_path))
        self._file_backups: dict[str, str] = {}

    def get_absolute_path(self, relative_path: str) -> Path:
        """Convert a relative path (from project root) to an absolute path."""
        return self.project_path / relative_path

    def read_file(self, relative_path: str) -> str:
        """
        Read the contents of a Lean file.

        Args:
            relative_path: Path relative to project root

        Returns:
            File contents as string
        """
        abs_path = self.get_absolute_path(relative_path)
        with open(abs_path) as f:
            return f.read()

    def write_file(self, relative_path: str, content: str) -> None:
        """
        Write content to a Lean file.

        Args:
            relative_path: Path relative to project root
            content: Content to write
        """
        abs_path = self.get_absolute_path(relative_path)
        # print(f"writing file to {abs_path}")
        with open(abs_path, "w") as f:
            f.write(content)

    def replace_code(
        self, relative_path: str, old_code: str, new_code: str, backup: bool = False, verify: bool = True
    ) -> tuple[bool, int | None, int | None]:
        """
        Replace code in a Lean file.

        Args:
            relative_path: Path relative to project root
            old_code: Code to be replaced
            new_code: New code to insert
            backup: Whether to backup the original content (default: True)
            verify: Whether to verify old_code exists before replacing (default: True)

        Returns:
            Tuple of (success, start_line, end_line) where:
                - success: True if replacement was successful, False otherwise
                - start_line: Zero-based line number where new code starts (None if failed)
                - end_line: Zero-based line number where new code ends (None if failed)
        """
        # print(f"replacing code in {relative_path}")
        content = self.read_file(relative_path)

        # Backup original content if requested
        if backup and relative_path not in self._file_backups:
            self._file_backups[relative_path] = content

        # Find the position where old_code starts
        start_pos = content.find(old_code)
        if start_pos == -1:
            return False, None, None

        # Verify old code exists (redundant check if verify=True, but keeps original behavior)
        if verify and old_code not in content:
            return False, None, None

        # Calculate the start line (zero-based) by counting newlines before start_pos
        start_line = content[:start_pos].count("\n")

        # Calculate the end line based on new_code (zero-based)
        # If new_code ends with \n, that newline terminates the last line, not starts a new one
        new_code_line_count = new_code.count("\n")
        if new_code.endswith("\n"):
            end_line = start_line + new_code_line_count - 1
        else:
            end_line = start_line + new_code_line_count

        # Replace and write (replace only first occurrence)
        new_content = content.replace(old_code, new_code, 1)
        self.write_file(relative_path, new_content)
        return True, start_line, end_line

    def restore_file(self, relative_path: str) -> bool:
        """
        Restore a file from backup.

        Args:
            relative_path: Path relative to project root

        Returns:
            True if restore was successful, False if no backup exists
        """
        if relative_path not in self._file_backups:
            return False

        self.write_file(relative_path, self._file_backups[relative_path])
        del self._file_backups[relative_path]
        return True

    def get_diagnostics(
        self, relative_path: str, start_line: int = None, end_line: int = None, timeout: int = 15
    ) -> Any:
        """
        Get Lean server diagnostics for a file.

        Args:
            relative_path: Path relative to project root
            start_line: Optional start line for filtering (0-indexed)
            end_line: Optional end line for filtering (0-indexed, inclusive)
            timeout: Timeout in seconds for waiting for diagnostics

        Returns:
            Diagnostics result from Lean server
        """
        # print(f"getting diagnostics for {relative_path}")
        # print(f"getting diagnostics for {relative_path}, start_line: {start_line}, end_line: {end_line}, timeout: {timeout}")
        return self.client.get_diagnostics(
            relative_path, start_line=start_line, end_line=end_line, inactivity_timeout=timeout
        )

    def clear_backups(self) -> None:
        """Clear all file backups."""
        self._file_backups.clear()

    def close(self) -> None:
        """Close the Lean client connection."""
        self.client.close()

    @staticmethod
    def get_error_str(code, errors, error_thres=True):
        err_str = ""
        code_lines = code.split("\n")
        token_lengths = [len(line) + 1 for line in code_lines]

        error_num_thres = 1 if error_thres else len(errors) #debugging

        for i, error in enumerate(errors[:error_num_thres]):
            if "severity" not in error or "range" not in error:
                continue
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

    def check_correctness(self, diagnostics: Any) -> bool:
        """
        Check if the diagnostics are correct.

        Args:
            diagnostics: Diagnostics result from Lean server

        Returns:
            True if the diagnostics are correct, False otherwise
            Raise exception if system error

        """
        if len(diagnostics) == 0 and diagnostics.success:
            return True
        elif (
            len(diagnostics) == 1
            and "source" not in diagnostics[0]
            and "severity" not in diagnostics[0]
            and "range" not in diagnostics[0]
            and not diagnostics.success
        ):
            print(f"verifier error: potential system error, diagnostics: {diagnostics}", flush=True)
            raise Exception("potential system error")
        else:
            for error in diagnostics:
                if error["severity"] == 1 or (
                    error["severity"] == 2 and error["message"] == "declaration uses 'sorry'"
                ):
                    return False
        if not diagnostics.success:
            # New thing in leanclient updated version: If in this case, then errors come from other parts of the file that we didn't change. Need to get diagnostics for the whole file.
            return False
        return True

    def init_temp_file(self, original_relative_path: str, id: str = None) -> str:
        """
        Initialize a temporary file with the original content.

        Args:
            original_relative_path: Path relative to project root
            id: Unique identifier for the temp file

        Returns:
            Relative path to the temporary file
        """
        original_content = self.read_file(original_relative_path)
        ts = time.strftime("%Y%m%d_%H%M%S", time.localtime())

        orig_path = Path(original_relative_path)
        dir_path = orig_path.parent
        filename = orig_path.stem
        suffix = orig_path.suffix

        new_filename = f"temp_{id}_{ts}_{filename}{suffix}"
        new_relative_path = dir_path / new_filename
        self.write_file(new_relative_path.as_posix(), original_content)
        return new_relative_path.as_posix()

    def init_standalone_temp_file(self, base_relative_path: str, id: str, content: str) -> str:
        """
        Create a temporary file with custom content for standalone proof verification.

        Unlike init_temp_file which copies an existing file, this creates a new file
        with the provided content. Used for verifying complete proof files that include
        their own preamble/imports.

        Args:
            base_relative_path: Path relative to project root to use as template for
                               determining the temp file location (e.g., "Mathlib/Tactic/Basic.lean")
            id: Unique identifier for the temp file
            content: The complete content to write to the temp file

        Returns:
            Relative path to the temporary file
        """
        ts = time.strftime("%Y%m%d_%H%M%S", time.localtime())

        orig_path = Path(base_relative_path)
        dir_path = orig_path.parent
        filename = orig_path.stem
        suffix = orig_path.suffix

        new_filename = f"standalone_{id}_{ts}_{filename}{suffix}"
        new_relative_path = dir_path / new_filename
        self.write_file(new_relative_path.as_posix(), content)
        return new_relative_path.as_posix()

    def remove_temp_file(self, temp_file_path: str) -> None:
        """
        Remove a temporary file.

        Args:
            temp_file_path: Relative path to the temporary file
        """
        abs_path = self.get_absolute_path(temp_file_path)
        if os.path.exists(abs_path):
            os.remove(abs_path)


