#!/usr/bin/env python3
"""Analyze codebase for consistency patterns - Batch 6 analysis."""

import ast
import re
from pathlib import Path


def analyze_type_hints(src_dir: str) -> dict:
    """Analyze type hint coverage in Python files."""
    results = {
        "total_functions": 0,
        "with_return_type": 0,
        "with_all_param_types": 0,
        "missing_hints": [],
    }

    for py_file in Path(src_dir).rglob("*.py"):
        if "__pycache__" in str(py_file):
            continue

        try:
            with open(py_file, "r", encoding="utf-8") as f:
                tree = ast.parse(f.read())
        except Exception:
            continue

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                results["total_functions"] += 1

                # Check return annotation
                has_return = node.returns is not None
                if has_return:
                    results["with_return_type"] += 1

                # Check parameter annotations (skip self/cls)
                params = [
                    arg for arg in node.args.args if arg.arg not in ("self", "cls")
                ]
                all_params_typed = (
                    all(arg.annotation is not None for arg in params)
                    if params
                    else True
                )
                if all_params_typed:
                    results["with_all_param_types"] += 1

                if not has_return or not all_params_typed:
                    rel_path = py_file.relative_to(Path(src_dir).parent)
                    results["missing_hints"].append(
                        f"{rel_path}:{node.lineno}:{node.name}"
                    )

    return results


def analyze_naming_conventions(src_dir: str) -> dict:
    """Analyze naming convention compliance."""
    results = {
        "snake_case_functions": 0,
        "camel_case_classes": 0,
        "uppercase_constants": 0,
        "violations": [],
    }

    snake_case_pattern = re.compile(r"^_*[a-z][a-z0-9_]*$")
    camel_case_pattern = re.compile(r"^_*[A-Z][a-zA-Z0-9]*$")

    for py_file in Path(src_dir).rglob("*.py"):
        if "__pycache__" in str(py_file):
            continue

        try:
            with open(py_file, "r", encoding="utf-8") as f:
                content = f.read()
                tree = ast.parse(content)
        except Exception:
            continue

        rel_path = py_file.relative_to(Path(src_dir).parent)

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if snake_case_pattern.match(node.name):
                    results["snake_case_functions"] += 1
                else:
                    results["violations"].append(
                        f"{rel_path}:{node.lineno}: Function '{node.name}' not snake_case"
                    )

            elif isinstance(node, ast.ClassDef):
                if camel_case_pattern.match(node.name):
                    results["camel_case_classes"] += 1
                else:
                    results["violations"].append(
                        f"{rel_path}:{node.lineno}: Class '{node.name}' not CamelCase"
                    )

    return results


def analyze_error_handling(src_dir: str) -> dict:
    """Analyze error handling patterns."""
    results = {
        "total_try_blocks": 0,
        "bare_excepts": 0,
        "broad_exceptions": 0,
        "specific_exceptions": 0,
        "issues": [],
    }

    for py_file in Path(src_dir).rglob("*.py"):
        if "__pycache__" in str(py_file):
            continue

        try:
            with open(py_file, "r", encoding="utf-8") as f:
                tree = ast.parse(f.read())
        except Exception:
            continue

        rel_path = py_file.relative_to(Path(src_dir).parent)

        for node in ast.walk(tree):
            if isinstance(node, ast.Try):
                results["total_try_blocks"] += 1

                for handler in node.handlers:
                    if handler.type is None:
                        results["bare_excepts"] += 1
                        results["issues"].append(
                            f"{rel_path}:{handler.lineno}: Bare except clause"
                        )
                    elif isinstance(handler.type, ast.Name):
                        if handler.type.id == "Exception":
                            results["broad_exceptions"] += 1
                        else:
                            results["specific_exceptions"] += 1

    return results


def analyze_logging(src_dir: str) -> dict:
    """Analyze logging patterns."""
    results = {
        "total_log_calls": 0,
        "f_string_logs": 0,
        "lazy_logs": 0,
        "structured_logs": 0,
        "issues": [],
    }

    for py_file in Path(src_dir).rglob("*.py"):
        if "__pycache__" in str(py_file):
            continue

        try:
            with open(py_file, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception:
            continue

        # Count logger calls
        log_patterns = re.findall(
            r"logger\.(debug|info|warning|error|critical)\s*\(", content
        )
        results["total_log_calls"] += len(log_patterns)

        # Check for f-string logging (performance issue)
        f_string_logs = re.findall(r'logger\.\w+\s*\(f["\']', content)
        results["f_string_logs"] += len(f_string_logs)

        # Check for lazy logging with %
        lazy_logs = re.findall(r'logger\.\w+\s*\("[^"]*%[sd]', content)
        results["lazy_logs"] += len(lazy_logs)

        # Check for structured logging (extra=)
        structured = re.findall(r"logger\.\w+\s*\([^)]*extra\s*=", content)
        results["structured_logs"] += len(structured)

    return results


def main():
    """Run all consistency analyses."""
    src_dir = "src"

    print("=" * 60)
    print("BATCH 6: CONSISTENCY & STANDARDS ANALYSIS")
    print("=" * 60)

    # Type hints analysis
    print("\n## Type Hints Analysis")
    type_results = analyze_type_hints(src_dir)
    print(f"Total functions: {type_results['total_functions']}")
    print(
        f"With return type: {type_results['with_return_type']} "
        f"({100*type_results['with_return_type']/max(1,type_results['total_functions']):.1f}%)"
    )
    print(
        f"With all param types: {type_results['with_all_param_types']} "
        f"({100*type_results['with_all_param_types']/max(1,type_results['total_functions']):.1f}%)"
    )
    print(f"Missing hints: {len(type_results['missing_hints'])}")

    # Naming conventions
    print("\n## Naming Conventions Analysis")
    naming_results = analyze_naming_conventions(src_dir)
    print(f"Snake case functions: {naming_results['snake_case_functions']}")
    print(f"CamelCase classes: {naming_results['camel_case_classes']}")
    print(f"Naming violations: {len(naming_results['violations'])}")
    if naming_results["violations"]:
        for v in naming_results["violations"][:5]:
            print(f"  - {v}")

    # Error handling
    print("\n## Error Handling Analysis")
    error_results = analyze_error_handling(src_dir)
    print(f"Total try blocks: {error_results['total_try_blocks']}")
    print(f"Bare excepts: {error_results['bare_excepts']}")
    print(f"Broad Exception catches: {error_results['broad_exceptions']}")
    print(f"Specific exceptions: {error_results['specific_exceptions']}")
    if error_results["issues"]:
        print(f"Issues found: {len(error_results['issues'])}")
        for issue in error_results["issues"][:5]:
            print(f"  - {issue}")

    # Logging
    print("\n## Logging Analysis")
    log_results = analyze_logging(src_dir)
    print(f"Total log calls: {log_results['total_log_calls']}")
    print(f"F-string logs (eager eval): {log_results['f_string_logs']}")
    print(f"Lazy logs (% formatting): {log_results['lazy_logs']}")
    print(f"Structured logs (extra=): {log_results['structured_logs']}")

    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    type_coverage = (
        100 * type_results["with_return_type"] / max(1, type_results["total_functions"])
    )
    print(f"Type hint coverage: {type_coverage:.1f}%")
    print(f"Naming convention violations: {len(naming_results['violations'])}")
    print(f"Error handling issues: {error_results['bare_excepts']}")
    print(
        f"Logging best practice compliance: {log_results['structured_logs']}/{log_results['total_log_calls']}"
    )


if __name__ == "__main__":
    main()
