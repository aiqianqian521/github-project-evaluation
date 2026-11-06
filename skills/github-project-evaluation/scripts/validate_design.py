#!/usr/bin/env python3
import re
import sys
from pathlib import Path


REQUIRED = {
    "FUNCTIONAL-TEST-DESIGN.md": (
        "项目画像与证据边界",
        "功能风险地图",
        "功能用例账本",
        "环境与准入",
        "执行顺序与判据",
        "准出与交付",
    ),
    "PRESSURE-TEST-DESIGN.md": (
        "负载对象与容量目标",
        "负载模型与工作负载",
        "场景与流量曲线",
        "环境数据与隔离",
        "观测与归因",
        "停机回滚与恢复",
        "判据与报告",
    ),
    "TEST-HANDOFF.md": (),
}


def validate(directory: Path) -> list[str]:
    issues = []
    for filename, headings in REQUIRED.items():
        path = directory / filename
        if not path.is_file():
            issues.append(f"missing: {path}")
            continue
        try:
            text = path.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeError) as exc:
            issues.append(f"unreadable: {path}: {type(exc).__name__}")
            continue
        found = re.findall(r"^## (.+)$", text, re.MULTILINE)
        positions = [found.index(heading) if heading in found else -1 for heading in headings]
        if -1 in positions or positions != sorted(positions):
            issues.append(f"missing or out-of-order headings: {path}")
        prefix = "F" if filename.startswith("FUNCTIONAL") else "P" if filename.startswith("PRESSURE") else None
        if prefix:
            rows = re.findall(rf"^\|\s*{prefix}-[A-Za-z0-9-]+\s*\|.*$", text, re.MULTILINE)
            case_ids = re.findall(rf"^\|\s*({prefix}-[A-Za-z0-9-]+)\s*\|", text, re.MULTILINE)
            if len(case_ids) < 2:
                issues.append(f"need at least two {prefix}- cases: {path}")
            if len(case_ids) != len(set(case_ids)):
                issues.append(f"duplicate {prefix}- case ID: {path}")
            for row in rows:
                cells = [cell.strip() for cell in row.strip().strip("|").split("|")]
                case_id = cells[0]
                minimum_fields = 6 if prefix == "F" else 5
                if (len(cells) < minimum_fields or any(not cell or cell.lower() in {"case", "todo", "tbd", "..."}
                                              for cell in cells[1:])):
                    issues.append(f"insufficient case details: {path}: {case_id}")
                if not re.search(r"\bNOT-RUN\b", cells[-1]):
                    issues.append(f"missing design-only case status: {path}: {case_id}")
                if re.search(r"\b(?:PASS|FAIL)\b", cells[-1]):
                    issues.append(f"executed verdict in design-only case status: {path}: {case_id}")
            portrait = text.split("## 项目画像与证据边界", 1)[-1].split("## ", 1)[0]
            if prefix == "F" and not re.search(r"`[^`]*[/\\][^`]+`", portrait):
                issues.append(f"missing source locator in project portrait: {path}")
            if prefix == "P":
                stop_section = text.split("## 停机回滚与恢复", 1)[-1].split("## ", 1)[0]
                if len(stop_section.strip()) < 40:
                    issues.append(f"missing actionable abort/recovery description: {path}")
        else:
            if "设计完成 ≠ 测试通过" not in text:
                issues.append(f"missing design-vs-execution distinction: {path}")
            if not re.search(r"^\|.*`[^`]+`.*\|", text, re.MULTILINE):
                issues.append(f"missing traceability source reference: {path}")
            lines = text.splitlines()
            headers = []
            for index, line in enumerate(lines):
                if not line.startswith("|"):
                    continue
                cells = [cell.strip().lower() for cell in line.strip("|").split("|")]
                if (len(cells) == 5 and "reviewer" in cells[1] and "evidence" in cells[2]
                        and "decision" in cells[3] and ("owner" in cells[4] or "retest" in cells[4])):
                    headers.append(index)
            if not headers:
                issues.append(f"independent review table missing: {path}")
            else:
                review_rows = []
                for line in lines[headers[0] + 1:]:
                    if not line.startswith("|"):
                        break
                    cells = [cell.strip() for cell in line.strip("|").split("|")]
                    if len(cells) == 5 and not all(re.fullmatch(r"[-: ]+", cell) for cell in cells):
                        review_rows.append(cells)
                if len({row[0] for row in review_rows if all(row)}) < 5:
                    issues.append(f"need five review checks with complete rows: {path}")
                categories = (r"source|源码|来源|引用", r"risk|风险", r"oracle|真值|判据",
                              r"load|slo|负载|容量|压力", r"redact|secret|脱敏|敏感")
                single_categories = []
                for row in review_rows:
                    matched = [index for index, category in enumerate(categories)
                               if re.search(category, row[0].lower())]
                    if len(matched) == 1:
                        single_categories.append(matched[0])
                if set(single_categories) != set(range(len(categories))):
                    issues.append(f"missing review categories: {path}")
                if (any("tbd" in " ".join(row).lower() or "待指定" in " ".join(row)
                        for row in review_rows) and "DESIGN-REVIEW-BLOCKED" not in text):
                    issues.append(f"unresolved reviews require DESIGN-REVIEW-BLOCKED: {path}")
    return issues


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: validate_design.py OUTPUT_DIR", file=sys.stderr)
        return 2
    issues = validate(Path(sys.argv[1]))
    if issues:
        print("\n".join(issues), file=sys.stderr)
        return 1
    print("Structure and case IDs OK; semantic truth and execution not verified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
