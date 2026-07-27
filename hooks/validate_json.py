"""Validate knowledge entry JSON files.

Usage:
    python hooks/validate_json.py <json_file> [json_file2 ...]
    python hooks/validate_json.py knowledge/articles/*.json

Exit 0 on all pass, exit 1 with error list + summary on any failure.
"""

import json
import re
import sys
from pathlib import Path

REQUIRED_FIELDS: dict[str, type] = {
    "id": str,
    "title": str,
    "source_url": str,
    "summary": str,
    "tags": list,
    "status": str,
}

ID_PATTERN = re.compile(
    r"^(github-trending|hackernews)"  # source
    r"-\d{8}"                          # YYYYMMDD
    r"-\d{3}$"                         # NNN
)

VALID_STATUSES = frozenset({"draft", "reviewed", "published", "archived"})
VALID_AUDIENCES = frozenset({"beginner", "intermediate", "advanced"})

URL_PATTERN = re.compile(r"^https?://\S+", re.IGNORECASE)


class ValidationError:
    def __init__(self, filepath: str, message: str):
        self.filepath = filepath
        self.message = message

    def __str__(self) -> str:
        return f"{self.filepath}: {self.message}"


def collect_files(paths: list[str]) -> list[Path]:
    """Collect all JSON files from the given paths, expanding glob wildcards."""
    collected: list[Path] = []
    seen: set[str] = set()
    for raw in paths:
        resolved = Path(raw).resolve()
        if "*" in resolved.name or "?" in resolved.name:
            matches = sorted(resolved.parent.glob(resolved.name))
        elif resolved.is_dir():
            matches = sorted(resolved.glob("*.json"))
        else:
            matches = [resolved]
        for p in matches:
            p_str = str(p)
            if p_str not in seen:
                seen.add(p_str)
                collected.append(p)
    return collected


def validate_file(filepath: Path) -> list[ValidationError]:
    """Run all validations on a single JSON file and return list of errors."""
    errors: list[ValidationError] = []
    fname = str(filepath)

    # 1) Parse JSON
    try:
        with open(filepath, encoding="utf-8") as fh:
            data = json.load(fh)
    except json.JSONDecodeError as exc:
        errors.append(ValidationError(fname, f"JSON 解析失败: {exc}"))
        return errors
    except OSError as exc:
        errors.append(ValidationError(fname, f"文件读取失败: {exc}"))
        return errors

    if not isinstance(data, dict):
        errors.append(ValidationError(fname, "根元素必须是 JSON 对象"))
        return errors

    # 2) Required fields existence + type
    for field, expected_type in REQUIRED_FIELDS.items():
        if field not in data:
            errors.append(ValidationError(fname, f"缺少必填字段: {field}"))
        elif not isinstance(data[field], expected_type):
            errors.append(
                ValidationError(
                    fname,
                    f"字段类型错误: {field} 期望 {expected_type.__name__}, "
                    f"实际 {type(data[field]).__name__}",
                )
            )

    # 3) ID format
    entry_id = data.get("id", "")
    if not ID_PATTERN.match(str(entry_id)):
        errors.append(
            ValidationError(
                fname,
                f"ID 格式错误: '{entry_id}' 不符合 "
                "{source}-{YYYYMMDD}-{NNN} 格式",
            )
        )

    # 4) Status enum
    status = data.get("status", "")
    if status not in VALID_STATUSES:
        errors.append(
            ValidationError(
                fname,
                f"status 值非法: '{status}'，合法值: {sorted(VALID_STATUSES)}",
            )
        )

    # 5) URL format
    source_url = data.get("source_url", "")
    if isinstance(source_url, str) and not URL_PATTERN.match(source_url):
        errors.append(
            ValidationError(fname, f"URL 格式错误: '{source_url}'")
        )

    # 6) Summary minimum length
    summary = data.get("summary", "")
    if isinstance(summary, str) and len(summary.strip()) < 20:
        errors.append(
            ValidationError(fname, f"摘要不足 20 字 (当前 {len(summary)} 字)")
        )

    # 7) Tags minimum count
    tags = data.get("tags", [])
    if isinstance(tags, list) and len(tags) < 1:
        errors.append(ValidationError(fname, "标签数量不足，至少需要 1 个"))

    # 8) Optional: score (1-10)
    score = data.get("score")
    if score is not None:
        if not isinstance(score, (int, float)):
            errors.append(
                ValidationError(fname, f"score 类型错误: {type(score).__name__}")
            )
        elif not (1 <= score <= 10):
            errors.append(
                ValidationError(fname, f"score 超出范围(1-10): {score}")
            )

    # 9) Optional: audience enum
    audience = data.get("audience")
    if audience is not None and audience not in VALID_AUDIENCES:
        errors.append(
            ValidationError(
                fname,
                f"audience 值非法: '{audience}'，"
                f"合法值: {sorted(VALID_AUDIENCES)}",
            )
        )

    return errors


def main() -> int:
    if len(sys.argv) < 2:
        print(f"用法: python {sys.argv[0]} <json_file> [json_file2 ...]", file=sys.stderr)
        return 1

    files = collect_files(sys.argv[1:])
    if not files:
        print("未匹配到任何 JSON 文件", file=sys.stderr)
        return 1

    total_errors = 0
    passed = 0
    failed = 0

    for fp in files:
        errors = validate_file(fp)
        if errors:
            failed += 1
            total_errors += len(errors)
            for err in errors:
                print(f"[错误] {err}", file=sys.stderr)
        else:
            passed += 1
            print(f"[通过] {fp}")

    print()
    print(f"文件总数: {len(files)}")
    print(f"通过: {passed}  |  失败: {failed}  |  错误数: {total_errors}")

    return 0 if total_errors == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
