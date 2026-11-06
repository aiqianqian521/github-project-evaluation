import tempfile
import unittest
from pathlib import Path

from validate_design import REQUIRED, validate


class DesignValidatorTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory(dir=Path.cwd())
        self.addCleanup(self.temporary_directory.cleanup)
        self.output_dir = Path(self.temporary_directory.name)
        for filename, headings in REQUIRED.items():
            content = "# Test design\n" + "\n".join(f"## {heading}" for heading in headings)
            if filename.startswith("FUNCTIONAL"):
                content = content.replace("## 项目画像与证据边界", "## 项目画像与证据边界\n`project/repo.py:1`", 1)
                content += "\n| F-01 | input valid | fixture A | independent value | log A | NOT-RUN |\n"
                content += "| F-02 | input invalid | fixture B | reject with no effect | log B | NOT-RUN |\n"
            elif filename.startswith("PRESSURE"):
                content = content.replace("## 停机回滚与恢复", "## 停机回滚与恢复\nStop on approved error ceiling, retain evidence and verify data recovery.", 1)
                content += "\n| P-01 | baseline tasks/min | fixture A | approved target TBD BLOCK | log A | NOT-RUN |\n"
                content += "| P-02 | recovery tasks/min | fixture B | stop at cost ceiling TBD BLOCK | log B | NOT-RUN |\n"
            else:
                content += "\n设计完成 ≠ 测试通过；DESIGN-REVIEW-BLOCKED\n| Source | `project/repo.py:1` | decision |\n"
                content += "\n| check | reviewer | independent evidence | decision | owner/retest condition |\n"
                content += "| --- | --- | --- | --- | --- |\n"
                for check in ("source existence", "risk-case mapping", "oracle independence", "load scope", "redaction"):
                    content += f"| {check} | TBD | pending review | BLOCK | owner to retest |\n"
            (self.output_dir / filename).write_text(content, encoding="utf-8")

    def test_valid_complete_example(self):
        self.assertEqual(validate(self.output_dir), [])

    def test_missing_document_is_rejected(self):
        (self.output_dir / "TEST-HANDOFF.md").unlink()
        self.assertIn("missing:", "\n".join(validate(self.output_dir)))

    def test_duplicate_case_id_is_rejected(self):
        path = self.output_dir / "FUNCTIONAL-TEST-DESIGN.md"
        text = path.read_text(encoding="utf-8")
        path.write_text(text.replace("| F-02 |", "| F-01 |"), encoding="utf-8")
        self.assertIn("duplicate F- case ID", "\n".join(validate(self.output_dir)))

    def test_hollow_cases_are_rejected(self):
        path = self.output_dir / "FUNCTIONAL-TEST-DESIGN.md"
        path.write_text(path.read_text().replace(
            "| F-01 | input valid | fixture A | independent value | log A | NOT-RUN |", "| F-01 | case |"),
            encoding="utf-8")
        self.assertIn("insufficient case details", "\n".join(validate(self.output_dir)))

    def test_missing_case_status_is_rejected(self):
        path = self.output_dir / "PRESSURE-TEST-DESIGN.md"
        path.write_text(path.read_text().replace("| NOT-RUN |", "| evidence |"), encoding="utf-8")
        self.assertIn("missing design-only case status", "\n".join(validate(self.output_dir)))

    def test_mixed_executed_verdict_is_rejected(self):
        path = self.output_dir / "FUNCTIONAL-TEST-DESIGN.md"
        path.write_text(path.read_text().replace("| NOT-RUN |", "| PASS NOT-RUN |", 1), encoding="utf-8")
        self.assertIn("executed verdict in design-only case status", "\n".join(validate(self.output_dir)))

    def test_review_table_cannot_be_omitted(self):
        path = self.output_dir / "TEST-HANDOFF.md"
        path.write_text(path.read_text().split("| check |", 1)[0], encoding="utf-8")
        self.assertIn("independent review table", "\n".join(validate(self.output_dir)))

    def test_missing_review_row_is_rejected(self):
        path = self.output_dir / "TEST-HANDOFF.md"
        path.write_text(path.read_text().replace("| redaction | TBD | pending review | BLOCK | owner to retest |", ""),
                        encoding="utf-8")
        self.assertIn("five review checks", "\n".join(validate(self.output_dir)))

    def test_five_unrelated_review_rows_are_rejected(self):
        path = self.output_dir / "TEST-HANDOFF.md"
        original = path.read_text(encoding="utf-8")
        for index, check in enumerate(("source existence", "risk-case mapping", "oracle independence", "load scope", "redaction")):
            original = original.replace(f"| {check} |", f"| generic {index} |")
        path.write_text(original, encoding="utf-8")
        self.assertIn("missing review categories", "\n".join(validate(self.output_dir)))

    def test_one_row_cannot_claim_all_five_reviews(self):
        path = self.output_dir / "TEST-HANDOFF.md"
        original = path.read_text(encoding="utf-8")
        for index, check in enumerate(("source existence", "risk-case mapping", "oracle independence", "load scope", "redaction")):
            original = original.replace(f"| {check} |", f"| {'source risk oracle load redaction' if index == 0 else f'generic {index}'} |")
        path.write_text(original, encoding="utf-8")
        self.assertIn("missing review categories", "\n".join(validate(self.output_dir)))

    def test_review_header_must_include_owner_or_retest(self):
        path = self.output_dir / "TEST-HANDOFF.md"
        path.write_text(path.read_text().replace(
            "| check | reviewer | independent evidence | decision | owner/retest condition |",
            "| review | reviewer | evidence | decision |"), encoding="utf-8")
        self.assertIn("independent review table", "\n".join(validate(self.output_dir)))

    def test_underspecified_case_is_rejected(self):
        path = self.output_dir / "FUNCTIONAL-TEST-DESIGN.md"
        path.write_text(path.read_text().replace(
            "| F-01 | input valid | fixture A | independent value | log A | NOT-RUN |",
            "| F-01 | input valid | independent value | evidence NOT-RUN |"), encoding="utf-8")
        self.assertIn("insufficient case details", "\n".join(validate(self.output_dir)))

    def test_blocked_is_not_executed_status(self):
        path = self.output_dir / "PRESSURE-TEST-DESIGN.md"
        path.write_text(path.read_text().replace("| NOT-RUN |", "| BLOCK |"), encoding="utf-8")
        self.assertIn("missing design-only case status", "\n".join(validate(self.output_dir)))

    def test_invalid_utf8_reports_clean_error(self):
        (self.output_dir / "TEST-HANDOFF.md").write_bytes(b"\xff")
        self.assertIn("unreadable", "\n".join(validate(self.output_dir)))


if __name__ == "__main__":
    unittest.main()
