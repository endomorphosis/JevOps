import argparse
import glob
import json
import os
import re
import shutil
import subprocess
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from lean_refactor.utils import proof_length, remove_comments


def check_lake_exists():
    """Check if lake command is available."""
    try:
        subprocess.run(["lake", "--version"], capture_output=True, check=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def build_lean_project(project_dir):
    """
    Build the Lean project using lake commands.
    Follows the same pattern as extract_repos.py: lake update -> lake exe cache get -> lake build
    """
    print(f"Building Lean project at {project_dir} to ensure the correctness of the provided .lean files")

    # Check if lake exists
    if not check_lake_exists():
        raise RuntimeError("Error running lake --version. Ensure lake is working before running this script.")

    # Clean up any existing lake artifacts
    lake_dir = os.path.join(project_dir, ".lake")
    lake_packages = os.path.join(project_dir, "lake-packages")
    lake_manifest = os.path.join(project_dir, "lake-manifest.json")

    for path in [lake_dir, lake_packages, lake_manifest]:
        if os.path.exists(path):
            if os.path.isdir(path):
                shutil.rmtree(path)
            else:
                os.remove(path)
            print(f"Removed existing {path}")

    # Run lake update
    print("Running lake update...")
    try:
        subprocess.run(["lake", "update"], cwd=project_dir, check=True)
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"'lake update' failed in {project_dir}. Please check the project configuration.") from e

    # Try to get mathlib cache (may fail if mathlib is not a dependency, which is fine)
    print("Running lake exe cache get...")
    try:
        subprocess.run(["lake", "exe", "cache", "get"], cwd=project_dir, check=True)
    except subprocess.CalledProcessError:
        print("'lake exe cache get' failed (mathlib may not be a dependency). Continuing...")

    # Run lake build
    print("Running lake build...")
    try:
        subprocess.run(["lake", "build"], cwd=project_dir, check=True)
    except subprocess.CalledProcessError as e:
        raise RuntimeError(
            f"'lake build' failed in {project_dir}. "
            f"This likely means there are errors in your .lean files. "
            f"Please check the build output above for details."
        ) from e

    print(f"Successfully built Lean project at {project_dir}")


def create_lean_project(input_dir, output_dir, mathlib_version="v4.26.0", build=True):
    """
    Creates a Lean 4 project structure from a directory of .lean files.

    Args:
        input_dir: Directory containing .lean files
        output_dir: Output directory for the Lean project
        mathlib_version: Mathlib version to use (default: v4.26.0)
        build: Whether to build the project after creation (default: True)
    """

    # Check if lake exists before doing anything
    if build and not check_lake_exists():
        raise RuntimeError("'lake' command not found. Please ensure Lean 4 / Lake is installed and in PATH.")

    # Ensure output directory exists
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
        print(f"Created output directory: {output_dir}")
    else:
        raise ValueError(f"Output directory {output_dir} already exists")

    # Project setup
    project_name = "lean_project"
    lib_name = "LeanProject"

    # Create lean-toolchain
    toolchain_content = f"leanprover/lean4:{mathlib_version}"
    with open(os.path.join(output_dir, "lean-toolchain"), "w") as f:
        f.write(toolchain_content)
    print(f"Created lean-toolchain with version: {mathlib_version}")

    # Create lakefile.lean
    lakefile_content = f"""import Lake
open Lake DSL

package «{project_name}» where
  -- add any additional package configuration options here

require mathlib from git
  "https://github.com/leanprover-community/mathlib4.git" @ "{mathlib_version}"

@[default_target]
lean_lib «{lib_name}» where
  -- add any library configuration options here
"""
    with open(os.path.join(output_dir, "lakefile.lean"), "w") as f:
        f.write(lakefile_content)
    print("Created lakefile.lean")

    # Create project directory
    lib_dir = os.path.join(output_dir, lib_name)
    if not os.path.exists(lib_dir):
        os.makedirs(lib_dir)

    # Copy and Sanitize .lean files
    lean_files = [f for f in os.listdir(input_dir) if f.endswith(".lean")]
    imported_modules = []

    print(f"Processing {len(lean_files)} .lean files...")

    for filename in lean_files:
        base_name = os.path.splitext(filename)[0]
        # Basic sanitization: replace non-alphanumeric (except underscore) with underscore
        safe_name = re.sub(r"[^a-zA-Z0-9_]", "_", base_name)

        # Ensure it doesn't start with a number
        if safe_name[0].isdigit():
            safe_name = "_" + safe_name

        dest_filename = safe_name + ".lean"
        src_path = os.path.join(input_dir, filename)
        dest_path = os.path.join(lib_dir, dest_filename)

        shutil.copy2(src_path, dest_path)

        # Add to imports list
        imported_modules.append(f"{lib_name}.{safe_name}")

    # Create Root Library File
    # named {LibName}.lean at the top level
    root_lib_file = os.path.join(output_dir, f"{lib_name}.lean")

    with open(root_lib_file, "w") as f:
        f.write(f"-- This module serves as the root of the `{lib_name}` library.\n")
        f.write("-- Import modules here that should be built as part of the library.\n")
        for module in sorted(imported_modules):
            f.write(f"import {module}\n")

    print(f"Created root file {lib_name}.lean with {len(imported_modules)} imports.")

    # Build the project if requested
    if build:
        build_lean_project(output_dir)


def process_extracted_data(extraction_output_dir: str, project_root: str):
    """
    Process extracted Declarations and Premises to generate evaluation data.

    Args:
        extraction_output_dir: Directory containing 'Declarations' and 'Premises' subdirectories.
        project_root: Root directory of the Lean project (used to verify file existence and output path).
    """
    declarations_dir = os.path.join(extraction_output_dir, "Declarations")
    premises_dir = os.path.join(extraction_output_dir, "Premises")

    if not os.path.exists(declarations_dir) or not os.path.exists(premises_dir):
        raise ValueError(f"Declarations or Premises directory not found in {extraction_output_dir}")

    # Map: name -> {module, src, signature, kind, ...}
    declaration_map = {}

    # Iterate over jsonl files in Declarations
    decl_files = glob.glob(os.path.join(declarations_dir, "*.jsonl"))
    for file_path in decl_files:
        with open(file_path) as f:
            for line in f:
                try:
                    data = json.loads(line)
                    name = data.get("name")
                    if name:
                        module_name = data.get("module", "")
                        if not module_name:
                            continue
                        # Turn module into relative path: e.g. "LeanProject.numinav1_5_atf_480756" -> "LeanProject/numinav1_5_atf_480756.lean"
                        module_path = module_name.replace(".", os.sep) + ".lean"

                        data["module_path"] = module_path
                        declaration_map[name] = data
                except json.JSONDecodeError:
                    continue

    count = sum(1 for d in declaration_map.values() if d.get("kind") == "theorem")
    print(f"Loaded {len(declaration_map)} declarations, {count} of which are theorems/lemmas")

    # Map: name -> list of dependents (names)
    premise_map = {}

    prem_files = glob.glob(os.path.join(premises_dir, "*.jsonl"))
    for file_path in prem_files:
        with open(file_path) as f:
            for line in f:
                try:
                    data = json.loads(line)
                    name = data.get("name")
                    dependents = data.get("dependents", [])

                    if name:
                        dependent_names = [d.get("name") for d in dependents] if dependents else []
                        premise_map[name] = dependent_names
                except json.JSONDecodeError:
                    continue

    output_items = []

    # We iterate over the declaration items again (or filtered ones)
    for name, decl_info in declaration_map.items():
        kind = decl_info.get("kind")
        if kind != "theorem":
            continue

        module_path = decl_info.get("module_path")
        full_src_path = os.path.join(project_root, module_path)

        # Check if src file exists
        if not os.path.exists(full_src_path):
            print(f"Warning: Source file {full_src_path} does not exist. Skipping {name}.")
            continue
        else:
            with open(full_src_path) as f:
                content = f.read()
                if not decl_info.get("src") or decl_info.get("src") not in content:
                    print(
                        f"Warning: Source {decl_info.get('src')} not found in {full_src_path}. Skipping {name}. Possibly due to extraction errors."
                    )
                    continue

        # Resolve dependencies
        dependents = premise_map.get(name, [])
        contexts = []
        for dep_name in dependents:
            if dep_name in declaration_map:
                dep_info = declaration_map[dep_name]
                contexts.append({
                    "name": dep_name,
                    "kind": dep_info.get("kind"),
                    "signature": dep_info.get("signature"),
                    "src": dep_info.get("src"),
                })

        src = decl_info.get("src")

        # Filter out theorems with 'sorry'
        if "sorry" in remove_comments(src):
            print(f"Skipping {name} as it contains 'sorry'.")
            continue

        # Calculate proof length and skip if errors encountered
        plen = proof_length(src)
        if plen >= 10**9:
            print(
                f"Warning: Errors encountered during proof length calculation for {name} from {full_src_path}. Skipping {name}."
            )
            continue

        output_items.append({
            "name": name,
            "path": module_path,
            "proof_length": plen,
            "src": src,
            "signature": decl_info.get("signature"),
            "contexts": contexts,
        })

    # 4. Write Output
    if not output_items:
        print("No items to write to output.")
        return

    # json name: eval_{folder_name}.jsonl
    project_folder_name = os.path.basename(project_root.rstrip(os.sep))
    eval_dir = os.path.join(project_root, "eval")

    if not os.path.exists(eval_dir):
        os.makedirs(eval_dir)
    else:
        print(f"Warning: eval directory {eval_dir} already exists. Removing it and creating a new one.")
        shutil.rmtree(eval_dir)
        os.makedirs(eval_dir)

    output_filename = f"eval_{project_folder_name}.jsonl"
    output_path = os.path.join(eval_dir, output_filename)

    print(f"Writing {len(output_items)} items to {output_path}")

    with open(output_path, "w") as f:
        for item in output_items:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")

    return output_path


if __name__ == "__main__":
    process_extracted_data(
        "/local-scratch1/jla1045/lean-refactor/lean_refactor/example_project3/extraction_output",
        "/local-scratch1/jla1045/lean-refactor/lean_refactor/example_project3",
    )
    exit(0)

    parser = argparse.ArgumentParser(description="Convert a folder of .lean files into a Lean 4 project.")
    parser.add_argument("input_dir", help="Path to the directory containing .lean files")
    parser.add_argument("--output_dir", help="Path to the output project directory (default: <input_dir>_project)")

    args = parser.parse_args()

    input_path = os.path.abspath(args.input_dir)
    if args.output_dir:
        output_path = os.path.abspath(args.output_dir)
    else:
        output_path = input_path.rstrip(os.sep) + "_project"

    if not os.path.exists(input_path):
        print(f"Error: Input directory '{input_path}' does not exist.")
        exit(1)

    print(f"Source: {input_path}")
    print(f"Destination: {output_path}")

    create_lean_project(input_path, output_path)
