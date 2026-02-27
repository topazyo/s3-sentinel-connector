from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml


@dataclass
class CheckResult:
    name: str
    passed: bool
    details: str


class LocalPackageValidator:
    def __init__(self, solution_root: Path) -> None:
        self.solution_root = solution_root
        self.results: list[CheckResult] = []

        self.package_file = self.solution_root / "Package.json"
        self.metadata_file = self.solution_root / "Metadata.json"
        self.release_notes_file = self.solution_root / "ReleaseNotes.md"
        self.workbook_file = self.solution_root / "Workbooks" / "S3SentinelConnector_OperationalOverview.json"
        self.workbook_metadata_file = self.solution_root / "Workbooks" / "S3SentinelConnector_OperationalOverview.metadata.json"
        self.analytic_rule_file = self.solution_root / "Analytic Rules" / "S3SentinelConnector_HighVolumeFirewallDenies.yaml"

    def run(self) -> int:
        self._check_required_files_exist()
        package_json = self._safe_read_json(self.package_file, "Package.json parse")
        metadata_json = self._safe_read_json(self.metadata_file, "Metadata.json parse")
        workbook_json = self._safe_read_json(self.workbook_file, "Workbook JSON parse")
        workbook_metadata_json = self._safe_read_json(self.workbook_metadata_file, "Workbook metadata JSON parse")
        analytic_rule_yaml = self._safe_read_yaml(self.analytic_rule_file, "Analytics rule YAML parse")

        if package_json and metadata_json:
            self._check_version_and_publish_date_alignment(package_json, metadata_json)
            self._check_content_types(package_json)
            self._check_artifacts(package_json)

        if workbook_json:
            self._check_workbook_shape(workbook_json)

        if workbook_metadata_json:
            self._check_workbook_metadata_shape(workbook_metadata_json)

        if analytic_rule_yaml:
            self._check_analytic_rule_shape(analytic_rule_yaml)

        if package_json:
            self._check_release_notes_format(package_json)

        report_file = self._write_report()
        passed = sum(1 for result in self.results if result.passed)
        failed = len(self.results) - passed
        print(f"Validation complete: {passed} passed, {failed} failed")
        print(f"Report: {report_file}")
        return 0 if failed == 0 else 1

    def _check_required_files_exist(self) -> None:
        required = [
            self.package_file,
            self.metadata_file,
            self.release_notes_file,
            self.workbook_file,
            self.workbook_metadata_file,
            self.analytic_rule_file,
            self.solution_root / "TemplateSpecs" / "mainTemplate.json",
            self.solution_root / "TemplateSpecs" / "createUiDefinition.json",
        ]
        missing = [str(path.relative_to(self.solution_root)) for path in required if not path.exists()]
        self.results.append(
            CheckResult(
                name="Required artifact files exist",
                passed=len(missing) == 0,
                details="All required files found" if not missing else f"Missing: {', '.join(missing)}",
            )
        )

    def _safe_read_json(self, file_path: Path, name: str) -> dict[str, Any] | None:
        try:
            data = json.loads(file_path.read_text(encoding="utf-8"))
            self.results.append(CheckResult(name=name, passed=True, details="Parsed successfully"))
            return data
        except Exception as exc:
            self.results.append(CheckResult(name=name, passed=False, details=str(exc)))
            return None

    def _safe_read_yaml(self, file_path: Path, name: str) -> dict[str, Any] | None:
        try:
            data = yaml.safe_load(file_path.read_text(encoding="utf-8"))
            self.results.append(CheckResult(name=name, passed=True, details="Parsed successfully"))
            return data
        except Exception as exc:
            self.results.append(CheckResult(name=name, passed=False, details=str(exc)))
            return None

    def _check_version_and_publish_date_alignment(self, package: dict[str, Any], metadata: dict[str, Any]) -> None:
        package_version = package.get("metadata", {}).get("version")
        metadata_version = metadata.get("Version")
        package_date = package.get("LastPublishDate")
        metadata_date = metadata.get("LastPublishDate")

        self.results.append(
            CheckResult(
                name="Version alignment (Package.json vs Metadata.json)",
                passed=package_version == metadata_version,
                details=f"Package={package_version}, Metadata={metadata_version}",
            )
        )
        self.results.append(
            CheckResult(
                name="LastPublishDate alignment",
                passed=package_date == metadata_date,
                details=f"Package={package_date}, Metadata={metadata_date}",
            )
        )

    def _check_content_types(self, package: dict[str, Any]) -> None:
        required_types = {"DataConnector", "Workbook", "AnalyticsRule"}
        actual = set(package.get("contentTypes", []))
        missing = sorted(required_types - actual)
        self.results.append(
            CheckResult(
                name="Package contentTypes include required types",
                passed=not missing,
                details="All required types present" if not missing else f"Missing: {', '.join(missing)}",
            )
        )

    def _check_artifacts(self, package: dict[str, Any]) -> None:
        artifacts = package.get("artifacts", [])
        required_artifacts = {
            ("DataConnector", "Data Connectors/"),
            ("Workbook", "Workbooks/"),
            ("AnalyticsRule", "Analytic Rules/"),
        }
        found_artifacts: set[tuple[str, str]] = set()
        for item in artifacts:
            if not isinstance(item, dict):
                continue
            item_type = item.get("type")
            source_path = item.get("source", {}).get("path") if isinstance(item.get("source"), dict) else None
            if isinstance(item_type, str) and isinstance(source_path, str):
                found_artifacts.add((item_type, source_path))
        missing = sorted(required_artifacts - found_artifacts)
        self.results.append(
            CheckResult(
                name="Package artifacts include required paths",
                passed=not missing,
                details="All required artifact mappings present" if not missing else f"Missing: {missing}",
            )
        )

    def _check_workbook_shape(self, workbook: dict[str, Any]) -> None:
        schema = str(workbook.get("$schema", ""))
        version = workbook.get("version")
        items = workbook.get("items")
        self.results.append(
            CheckResult(
                name="Workbook schema/version shape",
                passed=("schema/workbook.json" in schema and version == "Notebook/1.0" and isinstance(items, list)),
                details=f"schema={schema}, version={version}, items_type={type(items).__name__}",
            )
        )

    def _check_workbook_metadata_shape(self, workbook_metadata: dict[str, Any]) -> None:
        is_template = workbook_metadata.get("isTemplate") is True
        template_data = workbook_metadata.get("templateData", {})
        required_keys = {"version", "name", "description", "author", "source"}
        missing = sorted(key for key in required_keys if key not in template_data)
        self.results.append(
            CheckResult(
                name="Workbook metadata shape",
                passed=is_template and not missing,
                details="Workbook metadata valid" if is_template and not missing else f"Missing keys: {missing}",
            )
        )

    def _check_analytic_rule_shape(self, rule: dict[str, Any]) -> None:
        required_fields = [
            "id",
            "name",
            "description",
            "severity",
            "status",
            "requiredDataConnectors",
            "queryFrequency",
            "queryPeriod",
            "triggerOperator",
            "triggerThreshold",
            "tactics",
            "relevantTechniques",
            "query",
            "kind",
            "version",
        ]
        missing = [field for field in required_fields if field not in rule]
        self.results.append(
            CheckResult(
                name="Analytics rule required field coverage",
                passed=len(missing) == 0,
                details="All required fields present" if not missing else f"Missing: {', '.join(missing)}",
            )
        )

    def _check_release_notes_format(self, package: dict[str, Any]) -> None:
        release_notes = self.release_notes_file.read_text(encoding="utf-8")
        has_table_header = "| **Version** | **Date Modified (DD-MM-YYYY)** | **Change History** |" in release_notes
        target_version = package.get("metadata", {}).get("version", "")
        mentions_current_version = target_version in release_notes
        self.results.append(
            CheckResult(
                name="Release notes table format",
                passed=has_table_header and mentions_current_version,
                details=f"table_header={has_table_header}, includes_version({target_version})={mentions_current_version}",
            )
        )

    def _write_report(self) -> Path:
        report_path = self.solution_root / "Verification" / "PrePublish_Validation_Report.md"
        generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        passed = sum(1 for result in self.results if result.passed)
        failed = len(self.results) - passed

        lines = [
            "# Local Pre-Publish Validation Report",
            "",
            f"- Generated: {generated_at}",
            f"- Solution: {self.solution_root.name}",
            f"- Summary: {passed} passed / {failed} failed",
            "",
            "## Checks",
            "",
            "| Check | Status | Details |",
            "|-------|--------|---------|",
        ]

        for result in self.results:
            status = "✅ PASS" if result.passed else "❌ FAIL"
            details = result.details.replace("|", "\\|")
            lines.append(f"| {result.name} | {status} | {details} |")

        report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return report_path


def main() -> int:
    script_path = Path(__file__).resolve()
    solution_root = script_path.parent.parent
    validator = LocalPackageValidator(solution_root=solution_root)
    return validator.run()


if __name__ == "__main__":
    raise SystemExit(main())
