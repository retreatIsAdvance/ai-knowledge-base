"""Quality scoring for knowledge entry JSON files.

Usage:
    python hooks/check_quality.py <json_file> [json_file2 ...]
    python hooks/check_quality.py knowledge/articles/*.json

5-dimension weighted scoring (total 100), grade A/B/C.
Exit 1 if any entry scores C (< 60), else 0.
"""

import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# ── constants ────────────────────────────────────────────────────────────────

TECH_KEYWORDS = frozenset({
    "AI", "LLM", "GPT", "Claude", "agent", "RAG", "transformer",
    "embedding", "fine-tuning", "model", "inference", "模型", "智能",
    "推理", "训练", "微调", "架构", "多模态", "开源", "部署",
    "token", "prompt", "MCP", "benchmark",
})

STANDARD_TAGS = frozenset({
    "llm", "agent", "rag", "vector", "embedding", "transformer",
    "fine-tuning", "prompt", "langchain", "open-source", "framework",
    "deployment", "benchmark", "inference", "tool-use", "multimodal",
    "diffusion", "vision", "speech", "nlp", "tutorial", "research",
    "safety", "ethics",
})

BUZZWORDS_CN = frozenset({
    "赋能", "抓手", "闭环", "打通", "全链路", "底层逻辑",
    "颗粒度", "拉通", "沉淀", "强大的", "革命性的",
})

BUZZWORDS_EN = frozenset({
    "groundbreaking", "revolutionary", "game-changing", "cutting-edge",
    "best-in-class", "next-gen", "state-of-the-art", "unprecedented",
    "disruptive", "paradigm-shifting",
})

ID_PATTERN = re.compile(
    r"^(github-trending|hackernews)-\d{8}-\d{3}$"
)

URL_PATTERN = re.compile(r"^https?://\S+", re.IGNORECASE)

VALID_STATUSES = frozenset({"draft", "reviewed", "published", "archived"})

GRADE_THRESHOLDS = {"A": 80, "B": 60}

# ── dataclasses ──────────────────────────────────────────────────────────────


@dataclass
class DimensionScore:
    name: str
    score: float
    max_score: float
    details: list[str] = field(default_factory=list)


@dataclass
class QualityReport:
    filepath: Path
    dimensions: list[DimensionScore] = field(default_factory=list)
    details: list[str] = field(default_factory=list)

    @property
    def total_score(self) -> float:
        return round(sum(d.score for d in self.dimensions), 1)

    @property
    def grade(self) -> str:
        if self.total_score >= GRADE_THRESHOLDS["A"]:
            return "A"
        if self.total_score >= GRADE_THRESHOLDS["B"]:
            return "B"
        return "C"

    @property
    def total_max(self) -> float:
        return sum(d.max_score for d in self.dimensions)


# ── file collection ──────────────────────────────────────────────────────────


def collect_files(paths: list[str]) -> list[Path]:
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


# ── dimension scorers ────────────────────────────────────────────────────────


def _score_summary(data: dict) -> DimensionScore:
    summary = data.get("summary", "")
    content = data.get("content", "")
    text = f"{summary} {content}"
    points = 0.0
    details: list[str] = []

    length = len(summary.strip())
    if length >= 50:
        points += 20
    elif length >= 20:
        points += 12
        details.append(f"摘要 {length} 字，≥20 但不足 50 字")
    else:
        details.append(f"摘要仅 {length} 字，不足 20 字")

    hits = [kw for kw in TECH_KEYWORDS if kw in text]
    bonus = min(len(hits) * 1.5, 5.0)
    points += bonus
    if bonus < 5 and hits:
        details.append(f"命中技术关键词 {len(hits)} 个，奖励 +{bonus:.1f}")

    return DimensionScore("摘要质量", round(min(points, 25), 1), 25, details)


def _score_tech_depth(data: dict) -> DimensionScore:
    score = data.get("relevance_score", 0)
    if not isinstance(score, (int, float)):
        score = 0
    mapped = round(min(max(score, 1), 10) * 2.5, 1)
    return DimensionScore("技术深度", mapped, 25)


def _score_format(data: dict) -> DimensionScore:
    points = 0.0
    details: list[str] = []

    entry_id = data.get("id", "")
    if ID_PATTERN.match(str(entry_id)):
        points += 4
    else:
        details.append("id 格式不符")

    title = data.get("title", "")
    if isinstance(title, str) and title.strip():
        points += 4
    else:
        details.append("title 缺失")

    source_url = data.get("source_url", "")
    if isinstance(source_url, str) and URL_PATTERN.match(source_url):
        points += 4
    else:
        details.append("source_url 格式错误")

    status = data.get("status", "")
    if status in VALID_STATUSES:
        points += 4
    else:
        details.append(f"status 非法: '{status}'")

    collected = data.get("collected_at")
    analyzed = data.get("analyzed_at")
    if collected or analyzed:
        points += 4
    else:
        details.append("缺少时间戳")

    return DimensionScore("格式规范", points, 20, details)


def _score_tags(data: dict) -> DimensionScore:
    tags = data.get("tags", [])
    if not isinstance(tags, list):
        return DimensionScore("标签精度", 0, 15, ["tags 类型错误"])

    details: list[str] = []
    valid = [t for t in tags if t in STANDARD_TAGS]
    invalid = [t for t in tags if t not in STANDARD_TAGS]
    tag_count = len(valid)

    if tag_count == 0:
        points = 0
        details.append("无标准标签")
    elif 1 <= tag_count <= 3:
        points = 15
    elif 4 <= tag_count <= 5:
        points = 12
        details.append(f"{tag_count} 个标签，超过推荐 1-3 个")
    else:
        points = 9
        details.append(f"{tag_count} 个标签过多，建议精简至 1-3 个")

    if invalid:
        penalty = min(len(invalid) * 3.0, points)
        points -= penalty
        details.append(f"含 {len(invalid)} 个非标准标签: {invalid}")

    return DimensionScore("标签精度", round(max(points, 0), 1), 15, details)


def _score_buzzwords(data: dict) -> DimensionScore:
    summary = data.get("summary", "")
    content = data.get("content", "")
    text = f"{summary}\n{content}"

    hits_cn = [w for w in BUZZWORDS_CN if w in text]
    hits_en = [w.lower() for w in BUZZWORDS_EN if w.lower() in text.lower()]
    total_hits = len(hits_cn) + len(hits_en)

    penalty = min(total_hits * 3.0, 15.0)
    points = round(15 - penalty, 1)

    details: list[str] = []
    if hits_cn:
        details.append(f"中文空洞词: {hits_cn}")
    if hits_en:
        details.append(f"英文空洞词: {hits_en}")

    return DimensionScore("空洞词检测", max(points, 0.0), 15, details)


# ── scoring orchestrator ─────────────────────────────────────────────────────


def score_file(filepath: Path) -> Optional[QualityReport]:
    try:
        with open(filepath, encoding="utf-8") as fh:
            data = json.load(fh)
    except (json.JSONDecodeError, OSError) as exc:
        dims = [
            DimensionScore("摘要质量", 0, 25, [str(exc)]),
            DimensionScore("技术深度", 0, 25),
            DimensionScore("格式规范", 0, 20),
            DimensionScore("标签精度", 0, 15),
            DimensionScore("空洞词检测", 0, 15),
        ]
        return QualityReport(filepath=filepath, dimensions=dims)


    if not isinstance(data, dict):
        data = {}

    dims = [
        _score_summary(data),
        _score_tech_depth(data),
        _score_format(data),
        _score_tags(data),
        _score_buzzwords(data),
    ]

    return QualityReport(filepath=filepath, dimensions=dims)


# ── display helpers ──────────────────────────────────────────────────────────


def _progress_bar(ratio: float, width: int = 20) -> str:
    filled = round(ratio * width)
    bar = "█" * filled + "░" * (width - filled)
    pct = round(ratio * 100)
    return f"[{bar}] {pct:3d}%"


def _format_line(label: str, score: float, max_score: float, width: int = 30) -> str:
    bar = _progress_bar(score / max_score)
    return f"  {label:<{width}} {bar} {score:.1f}/{max_score:.0f}"


def print_report(report: QualityReport) -> None:
    fname = report.filepath.name
    grade = report.grade
    total_bar = _progress_bar(report.total_score / report.total_max)

    print(f"[等级 {grade}] {total_bar} {fname}")

    for dim in report.dimensions:
        print(_format_line(dim.name, dim.score, dim.max_score))
        for detail in dim.details:
            print(f"    → {detail}")

    print()


# ── main ─────────────────────────────────────────────────────────────────────


def main() -> int:
    if len(sys.argv) < 2:
        print(
            f"用法: python {sys.argv[0]} <json_file> [json_file2 ...]",
            file=sys.stderr,
        )
        return 1

    files = collect_files(sys.argv[1:])
    if not files:
        print("未匹配到任何 JSON 文件", file=sys.stderr)
        return 1

    reports: list[QualityReport] = []
    for fp in files:
        report = score_file(fp)
        if report is not None:
            reports.append(report)
            print_report(report)

    # summary
    total = len(reports)
    grades = {"A": 0, "B": 0, "C": 0}
    for r in reports:
        grades[r.grade] += 1

    avg_score = sum(r.total_score for r in reports) / total if total else 0

    print(f"文件总数: {total}")
    print(f"A 级 (≥80): {grades['A']}  |  B 级 (≥60): {grades['B']}  |  "
          f"C 级 (<60): {grades['C']}")
    print(f"平均分: {avg_score:.1f}")

    return 1 if grades["C"] > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
