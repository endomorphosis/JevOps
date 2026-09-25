import argparse
import glob
import os
import subprocess
from pathlib import Path

from preprocess_data import create_lean_project, process_extracted_data


def _lakefile(repo, commit, name, cwd, toolchain_version="main", local_project_path=None):
    # Build the require statement based on local vs remote project
    require_stmt = f'require {name} from "{local_project_path}"'

    contents = """import Lake
open Lake DSL

package «lean-training-data» {
  moreLeanArgs := #[
    "-Dlinter.unusedVariables=false",
    -- for supporting more lean versions, some usages in the code are deprecated
    -- a macro TODO is to make the code more future proof (e.g. name change of HashMap)
    "-Dlinter.deprecated=false"
  ]
}

require «doc-gen4» from git "https://github.com/leanprover/doc-gen4.git" @ "%s"

%s

@[default_target]
lean_lib TrainingData where

lean_lib temp where

lean_lib Examples where

@[default_target]
lean_exe training_data where
  root := `scripts.training_data
  supportInterpreter := true

@[default_target]
lean_exe full_proof_training_data where
  root := `scripts.full_proof_training_data
  supportInterpreter := true

@[default_target]
lean_exe state_comments where
  root := `scripts.state_comments
  supportInterpreter := true

@[default_target]
lean_exe premises where
  root := `scripts.premises
  supportInterpreter := true

@[default_target]
lean_exe training_data_with_premises where
  root := `scripts.training_data_with_premises
  supportInterpreter := true

@[default_target]
lean_exe add_imports where
  root := `scripts.add_imports
  supportInterpreter := true

@[default_target]
lean_exe all_modules where
  root := `scripts.all_modules
  supportInterpreter := true

@[default_target]
lean_exe declarations where
  root := `scripts.declarations
  supportInterpreter := true

@[default_target]
lean_exe imports where
  root := `scripts.imports
  supportInterpreter := true

@[default_target]
lean_exe update_hammer_blacklist where
  root := `scripts.update_hammer_blacklist
  supportInterpreter := true

@[default_target]
lean_exe add_premises where
  root := `scripts.add_premises
  supportInterpreter := true
""" % (toolchain_version, require_stmt)
    with open(os.path.join(cwd, "lakefile.lean"), "w") as f:
        f.write(contents)


def _examples(imports, cwd):
    contents = """
%s
""" % ("\n".join(["import %s" % i for i in imports]))
    with open(os.path.join(cwd, "Examples.lean"), "w") as f:
        f.write(contents)


def _lean_toolchain(lean, cwd):
    contents = """%s""" % (lean)
    with open(os.path.join(cwd, "lean-toolchain"), "w") as f:
        f.write(contents)


def _lake_update(cwd):
    if Path(os.path.join(cwd, ".lake")).exists():
        subprocess.run(["rm", "-rf", ".lake"], cwd=cwd, check=True)
    if Path(os.path.join(cwd, "lake-packages")).exists():
        subprocess.run(["rm", "-rf", "lake-packages"], cwd=cwd, check=True)
    if Path(os.path.join(cwd, "lake-manifest.json")).exists():
        subprocess.run(["rm", "-rf", "lake-manifest.json"], cwd=cwd, check=True)
    print("Running lake udpate ...")
    subprocess.run(["lake", "update"], check=True)


def _lake_build(cwd):
    print("Building...")
    # this depends on mathlib; if the package does not require mathlib it will fail
    try:
        subprocess.run(["lake", "exe", "cache", "get"], cwd=cwd, check=True)
    except subprocess.CalledProcessError:
        print(
            "'lake exe cache get' command failed. This is probably because mathlib is not a dependency. Continuing..."
        )
    subprocess.run(["lake", "build"], cwd=cwd, check=True)


def _get_imports(cwd, name, imports: list[str]) -> list[str]:
    import_modules = []
    for module in imports:
        # The lakefile can (*very rarely*) specify a glob pattern
        # The "glob:" prefix is user-added in the config (or see fetch_reservoir_index.py)
        if module.startswith("glob:"):
            pattern = module.removeprefix("glob:")
            # See Lake.Config.Glob
            if not pattern.endswith("+"):
                import_modules.append(pattern)
                continue
            elif pattern.endswith(".+"):
                pattern = pattern.removesuffix(".+") + "/**/*.lean"
            elif pattern.endswith(".*"):
                import_modules.append(pattern.removesuffix(".*"))
                pattern = pattern.removesuffix(".*") + "/**/*.lean"
            root_dir = os.path.join(cwd, ".lake", "packages", _unescape_lean_name(name))
            print(pattern, root_dir)
            for import_file_path in glob.glob(pattern, root_dir=root_dir, recursive=True):
                import_modules.append(import_file_path.removesuffix(".lean").replace(os.path.sep, "."))
        else:
            import_modules.append(module)
    print(f"All import modules: {import_modules}")
    return import_modules


def _unescape_lean_name(name: str):
    name = name.replace("«", "").replace("»", "")
    return name


# def _import_file(name, import_file, old_version):
#     name = name.replace('«', '').replace('»', '')
#     if old_version:
#         return os.path.join('lake-packages', name, import_file)
#     else:
#         return os.path.join('.lake', 'packages', name, import_file)


def _run(cwd, name, import_module, max_workers, flags, output_base_dir=None):
    if output_base_dir is None:
        output_base_dir = os.path.join("Examples", _unescape_lean_name(name))
    if max_workers is not None:
        flags.append("--max-workers")
        flags.append(str(max_workers))
    subprocess.run(
        [
            "python3",
            "%s/scripts/run_pipeline.py" % cwd,
            "--output-base-dir",
            output_base_dir,
            "--cwd",
            cwd,
            "--import-module",
            *import_module,
            "--name",
            _unescape_lean_name(name),
            *flags,
        ],
        check=True,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--cwd", default="/local-scratch1/jla1045/ntp-toolkit")
    parser.add_argument("--config", default="configs/config.json", help="config file")
    parser.add_argument(
        "--max-workers", default=None, type=int, help="maximum number of processes; defaults to number of processors"
    )
    parser.add_argument("--skip_setup", action="store_true")
    parser.add_argument("--skip_existing", action="store_true", help="Do not overwrite existing output .jsonl files")
    parser.add_argument("--training_data", action="store_true")
    parser.add_argument("--full_proof_training_data", action="store_true")
    parser.add_argument("--premises", action="store_true")
    parser.add_argument("--state_comments", action="store_true")
    parser.add_argument("--full_proof_training_data_states", action="store_true")
    parser.add_argument("--training_data_with_premises", action="store_true")
    parser.add_argument("--add_imports", action="store_true")
    parser.add_argument("--declarations", action="store_true")
    parser.add_argument("--imports", action="store_true")
    parser.add_argument("--convert_minictx", action="store_true")
    # Input mode flags (mutually exclusive)
    parser.add_argument(
        "--lean_files_input_mode",
        action="store_true",
        help="Input is a directory of .lean files (requires --input and --output)",
    )
    parser.add_argument(
        "--local_lean_project_input_mode",
        action="store_true",
        help="Input is an existing local Lean project (requires --input, --name, --imports)",
    )
    # Generic input/output paths
    parser.add_argument("--input", type=str, default=None, help="Input path (meaning depends on input mode)")
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Output path for packaged Lean project (only for --lean_files_input_mode)",
    )
    parser.add_argument(
        "--name",
        type=str,
        default=None,
        help="Package name for the Lean project (required for --local_lean_project_input_mode)",
    )
    parser.add_argument(
        "--import_modules",
        type=str,
        nargs="+",
        default=None,
        help="Base module name(s) as entry points (e.g., Mathlib, PrimeNumberTheoremAnd) (required for --local_lean_project_input_mode)",
    )
    parser.add_argument(
        "--mathlib-version",
        type=str,
        default="v4.26.0",
        help="Mathlib version to use for local project (default: v4.26.0)",
    )
    args = parser.parse_args()

    # Validate input mode
    input_modes = [args.lean_files_input_mode, args.local_lean_project_input_mode]
    num_modes_set = sum(input_modes)

    if num_modes_set == 0:
        parser.error("Must specify one input mode: --lean_files_input_mode or --local_lean_project_input_mode")
    if num_modes_set > 1:
        parser.error("Only one input mode can be specified")

    if args.lean_files_input_mode:
        if not args.input or not args.output:
            parser.error("--lean_files_input_mode requires both --input and --output")

    if args.local_lean_project_input_mode:
        if not args.input:
            parser.error("--local_lean_project_input_mode requires --input")
        if not args.name:
            parser.error("--local_lean_project_input_mode requires --name (package name)")
        if not args.import_modules:
            parser.error("--local_lean_project_input_mode requires --import_modules (base module entry points)")

    # Handle input mode logic
    if args.lean_files_input_mode:
        # Package .lean files from --input into a Lean project at --output
        input_path = os.path.abspath(args.input)
        output_path = os.path.abspath(args.output)

        print(
            f"\n\n\n==========Packaging .lean files from {input_path} into Lean project at {output_path}==========\n\n\n"
        )
        create_lean_project(input_path, output_path, mathlib_version=args.mathlib_version)
        print("\n\n\n==========Done packaging .lean files into Lean project==========\n\n\n")

        sources = [
            {
                "repo": "",
                "commit": args.mathlib_version,
                "lean": f"leanprover/lean4:{args.mathlib_version}",
                "name": "lean_project",
                "imports": ["LeanProject"],
            }
        ]
        local_project_path = output_path
        extraction_output_dir = os.path.join(output_path, "extraction_output")

    elif args.local_lean_project_input_mode:
        # Use existing Lean project at --input directly (skip create_lean_project)
        local_project_path = os.path.abspath(args.input)

        sources = [
            {
                "repo": "",
                "commit": args.mathlib_version,
                "lean": f"leanprover/lean4:{args.mathlib_version}",
                "name": args.name,
                "imports": args.import_modules,
            }
        ]
        extraction_output_dir = os.path.join(local_project_path, "extraction_output")

    else:
        # not a possible case
        parser.error("Must specify one input mode: --lean_files_input_mode or --local_lean_project_input_mode")

    flags = ["--task"]
    if args.training_data:
        flags.append("training_data")
    if args.full_proof_training_data:
        flags.append("full_proof_training_data")
    if args.premises:
        flags.append("premises")
    if args.state_comments:
        flags.append("state_comments")
    if args.full_proof_training_data_states:
        flags.append("full_proof_training_data_states")
    if args.training_data_with_premises:
        flags.append("training_data_with_premises")
    if args.add_imports:
        flags.append("add_imports")
    if args.declarations:
        flags.append("declarations")
    if args.imports:
        flags.append("imports")
    if args.convert_minictx:
        flags.append("convert_minictx")

    for source in sources:
        print("\n\n\n==========Extracting Local Project: %s==========\n\n\n" % (local_project_path))
        print(source)
        if not args.skip_setup:
            _lean_toolchain(lean=source["lean"], cwd=args.cwd)
            _lakefile(
                repo=source["repo"],
                commit=source["commit"],
                name=source["name"],
                cwd=args.cwd,
                toolchain_version=source["lean"].removeprefix("leanprover/lean4:"),
                local_project_path=local_project_path,
            )

            _lake_update(cwd=args.cwd)

            imports = _get_imports(args.cwd, source["name"], source["imports"])
            _examples(imports=imports, cwd=args.cwd)
            _lake_build(cwd=args.cwd)
        else:
            imports = _get_imports(args.cwd, source["name"], source["imports"])
        _run(
            cwd=args.cwd,
            name=source["name"],
            import_module=imports,
            # import_file=source['import_file'],
            # old_version=False if 'old_version' not in source else source['old_version'],
            max_workers=args.max_workers,
            flags=flags,
            output_base_dir=extraction_output_dir,
        )

        jsonl_path = extraction_output_dir
        if args.lean_files_input_mode or args.local_lean_project_input_mode:
            print("\n\n\n==========Processing extracted data for local project==========\n\n\n")
            jsonl_path = process_extracted_data(extraction_output_dir, local_project_path)

        print("\n\n\n==========Use this command to run the proof optimization==========\n\n\n")
        print(
            f"lean-refactor optimize --planner --proof-jsonl {jsonl_path} --output-path <OUTPUT_RESULTS_JSONL> --lean-workspace-path {local_project_path} --num-workers <NUM_WORKERS> 2>&1 | tee <LOG_FILE_PATH>"
        )
