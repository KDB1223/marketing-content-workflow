"""Command line: mcw run | score | compare | list-versions | list-runs | list-briefs | stats | failures | list-findings | list-drafts.

``mcw list-briefs`` inventories Brief files in a directory (default ``briefs/``).
It validates each file with the existing schema loader. It does not call a
model or write ``.mcw/runs``. The counts are how many strings each Brief
carries, not a score and not a conversion rate.

``mcw stats`` inventories saved runs from manifest.json and versions.json and
rolls up stored offline scores by Brief, backend, approval status, and channel.
It does not call a model or recompute the rubric. The numbers are not
conversion rates. New runs record channel on the index; older indexes without
a channel show as unknown.

``mcw failures`` lists saved runs whose latest version missed a full offline
content score, was rejected, or whose recommended draft has a stored checklist
failure or high-severity finding. It reads saved artifacts only.

``mcw list-findings`` inventories stored checklist findings for every draft in
the selected version, at every severity. It reads saved artifacts only and
does not recompute risk rules. The rows are not a conversion rate.

``mcw list-drafts`` catalogs every stored draft in the selected version,
including drafts that were not recommended. It reads saved artifacts only.
The numbers are stored offline content scores, not conversion rates.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from mcw import __version__
from mcw.briefs_inventory import list_briefs
from mcw.errors import MCWError
from mcw.fixtures import score_cases
from mcw.llm.mock import MockGenerator
from mcw.llm.openai_compat import DEFAULT_BASE_URL, DEFAULT_MODEL, OpenAICompatGenerator
from mcw.pipeline import RunResult, run_pipeline
from mcw.schema import brief_fingerprint, load_brief
from mcw.scoring.compare import render_comparison
from mcw.scoring.rubric import DIMENSIONS, OFFLINE_SCORE_NOTE, score_text
from mcw.stages.extract import extract
from mcw.store import (
    inventory_drafts,
    inventory_failures,
    inventory_findings,
    list_saved_runs,
    load_history,
    load_version_files,
    make_run_id,
    persist_run,
    prepare_version,
    rescore_version,
    run_dir,
    summarize_saved_runs,
)

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mcw",
        description=(
            "营销文案的 Brief → 提取 → 生成 → 风险检查 → 人工确认。"
            "离线内容分不是投放转化率。"
        ),
    )
    parser.add_argument("--version", action="version", version=f"mcw {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="执行一次流水线，并写入 .mcw/runs/<run_id>/")
    run.add_argument("brief", help="Brief YAML 或 JSON 路径")
    run.add_argument("--mock", action="store_true", help="使用确定性 MockGenerator，不访问网络")
    run.add_argument("--variants", type=int, default=3, help="变体数量，1 到 5，默认 3")
    run.add_argument("--out", default=".mcw", help="产物根目录，默认 .mcw")
    run.add_argument("--run-id", default=None, help="新建运行的 id")
    run.add_argument("--continue-run", default=None, help="在已有运行上追加一个版本")
    run.add_argument("--reviewer", default=None, help="本版提交人")
    run.add_argument("--comment", default=None, help="审阅备注。初稿以外的备注会进入提示词")
    run.add_argument("--approval", default=None, help="人工确认 JSON。不传则写入 pending 存根")
    run.add_argument("--base-url", default=None, help="覆盖 MCW_LLM_BASE_URL")
    run.add_argument("--model", default=None, help="覆盖 MCW_LLM_MODEL")
    run.add_argument("--json", action="store_true", dest="as_json", help="用 JSON 打印摘要")
    run.set_defaults(handler=cmd_run)

    score = sub.add_parser("score", help="按离线量表打分。--fixtures 可复现")
    score.add_argument("--fixtures", action="store_true", help="对内置用例打分，并与记录的分数对照")
    score.add_argument("--run", default=None, help="对某次运行的存档重新打分")
    score.add_argument("--version", default=None, help="配合 --run，默认最新版")
    score.add_argument("--brief", default=None, help="配合 --draft，Brief 路径")
    score.add_argument("--draft", default=None, help="纯文本稿件路径")
    score.add_argument("--out", default=".mcw")
    score.add_argument("--json", action="store_true", dest="as_json")
    score.set_defaults(handler=cmd_score)

    compare = sub.add_parser("compare", help="对照同一运行里的两个版本")
    compare.add_argument("run", help="run id")
    compare.add_argument("--left", required=True, help="左侧版本，例如 v1")
    compare.add_argument("--right", required=True, help="右侧版本，例如 v2")
    compare.add_argument("--out", default=".mcw")
    compare.add_argument("--json", action="store_true", dest="as_json")
    compare.set_defaults(handler=cmd_compare)

    listing = sub.add_parser("list-versions", help="列出一次运行的版本和审阅备注")
    listing.add_argument("run", help="run id")
    listing.add_argument("--out", default=".mcw")
    listing.add_argument("--json", action="store_true", dest="as_json")
    listing.set_defaults(handler=cmd_list)

    inventory = sub.add_parser("list-runs", help="列出已保存的运行、最新版本、确认状态和离线总分")
    inventory.add_argument("--out", default=".mcw")
    inventory.add_argument("--json", action="store_true", dest="as_json")
    inventory.set_defaults(handler=cmd_list_runs)

    briefs_help = "列出目录里的 Brief 文件、渠道和约束条数。不调用模型，也不写入运行。"
    briefs_cmd = sub.add_parser("list-briefs", help=briefs_help, description=briefs_help)
    briefs_cmd.add_argument("directory", nargs="?", default="briefs", help="Brief 目录，默认 briefs")
    briefs_cmd.add_argument("--channel", default=None, help="按渠道 id、中文名或别名过滤")
    briefs_cmd.add_argument("--id", dest="brief_id", default=None, help="按 Brief.id 精确过滤")
    briefs_cmd.add_argument("--json", action="store_true", dest="as_json", help="用 JSON 打印清点结果")
    briefs_cmd.set_defaults(handler=cmd_list_briefs)

    stats_help = (
        "按确认状态、Brief、后端和渠道汇总已存储的离线分数。"
        "各组给出次数和最小、最大、平均；没有渠道的旧索引记为 unknown；不是转化率。"
    )
    stats = sub.add_parser("stats", help=stats_help, description=stats_help)
    stats.add_argument("--out", default=".mcw")
    stats.add_argument("--json", action="store_true", dest="as_json")
    stats.set_defaults(handler=cmd_stats)

    failures_help = (
        "列出未满分、被驳回，或推荐稿清单未通过、含高风险项的已保存运行。"
        "只读存档，不调用模型，也不重算量表。"
    )
    failures = sub.add_parser("failures", help=failures_help, description=failures_help)
    failures.add_argument("run", nargs="?", default=None, help="只看这一次运行；默认扫描全部")
    failures.add_argument("--version", default=None, help="配合 run id，默认该运行的最新版")
    failures.add_argument("--out", default=".mcw")
    failures.add_argument("--json", action="store_true", dest="as_json")
    failures.set_defaults(handler=cmd_failures)

    findings_help = (
        "列出已保存清单里的发现，含全部草稿和全部严重级别。"
        "只读存档，不调用模型，也不重算规则。"
    )
    list_findings = sub.add_parser("list-findings", help=findings_help, description=findings_help)
    list_findings.add_argument("run", nargs="?", default=None, help="只看这一次运行；默认扫描全部")
    list_findings.add_argument("--version", default=None, help="配合 run id，默认该运行的最新版")
    list_findings.add_argument("--rule", default=None, help="按 rule_id 精确过滤")
    list_findings.add_argument("--severity", default=None, help="按严重级别精确过滤")
    list_findings.add_argument("--channel", default=None, help="按渠道 id、中文名或别名过滤")
    list_findings.add_argument("--draft", default=None, help="按 draft_id 精确过滤")
    list_findings.add_argument("--brief", dest="brief_id", default=None, help="按 Brief.id 精确过滤")
    list_findings.add_argument("--out", default=".mcw")
    list_findings.add_argument("--json", action="store_true", dest="as_json")
    list_findings.set_defaults(handler=cmd_list_findings)

    drafts_help = (
        "列出已保存的全部文案变体、离线总分和清单状态，含未推荐稿。"
        "只读存档，不调用模型，也不重算量表。"
    )
    list_drafts = sub.add_parser("list-drafts", help=drafts_help, description=drafts_help)
    list_drafts.add_argument("run", nargs="?", default=None, help="只看这一次运行；默认扫描全部")
    list_drafts.add_argument("--version", default=None, help="配合 run id，默认该运行的最新版")
    list_drafts.add_argument("--draft", default=None, help="按 draft id 精确过滤")
    list_drafts.add_argument("--variant", default=None, help="按变体精确过滤")
    list_drafts.add_argument("--channel", default=None, help="按渠道 id、中文名或别名过滤")
    list_drafts.add_argument("--brief", dest="brief_id", default=None, help="按 Brief.id 精确过滤")
    list_drafts.add_argument("--out", default=".mcw")
    list_drafts.add_argument("--json", action="store_true", dest="as_json")
    list_drafts.set_defaults(handler=cmd_list_drafts)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        code = exc.code
        return 2 if code is None else int(code)
    try:
        return int(args.handler(args))
    except MCWError as exc:
        print(str(exc), file=sys.stderr)
        return 2


def cmd_run(args: argparse.Namespace) -> int:
    if args.run_id and args.continue_run:
        raise MCWError("请只提供 --run-id 或 --continue-run 其中之一")
    brief_path = Path(args.brief)
    brief = load_brief(brief_path)
    created_at = _now()
    out = Path(args.out)
    if args.continue_run:
        run_id = args.continue_run
        version = prepare_version(
            out,
            run_id,
            brief.id,
            brief_fingerprint(brief),
            continue_run=True,
        )
    else:
        run_id = args.run_id or make_run_id(brief.id, created_at)
        version = prepare_version(
            out,
            run_id,
            brief.id,
            brief_fingerprint(brief),
            continue_run=False,
        )
    generator = _generator(args)
    result = run_pipeline(
        brief,
        run_id=run_id,
        version=version,
        generator=generator,
        created_at=created_at,
        reviewer=args.reviewer,
        comment=args.comment,
        approval_path=args.approval,
        variants=args.variants,
        brief_path=str(brief_path),
    )
    directory = persist_run(out, result)
    _print_run(result, directory, args.as_json)
    return 0


def cmd_score(args: argparse.Namespace) -> int:
    modes = [bool(args.fixtures), bool(args.run), bool(args.draft or args.brief)]
    if sum(modes) != 1:
        raise MCWError("请在 --fixtures、--run、--brief/--draft 三种方式里选一种")
    if args.fixtures:
        return _score_fixtures(args.as_json)
    if args.run:
        payload, drifts = rescore_version(Path(args.out), args.run, args.version)
        if args.as_json:
            print(json.dumps({"result": payload, "drifts": drifts}, ensure_ascii=False, indent=2))
        else:
            print(f"run_id: {payload['run_id']}")
            print(f"version: {payload['version']}")
            for row in payload["drafts"]:
                dims = row["score"]["dimensions"]
                parts = " ".join(f"{item['label']}{item['score']}" for item in dims.values())
                print(f"{row['variant']} {row['draft_id']} {parts} 总分{row['score']['overall']}")
            print(f"note: {payload['note']}")
            if drifts:
                print("score drift: " + ", ".join(drifts), file=sys.stderr)
        return 1 if drifts else 0
    if not args.brief or not args.draft:
        raise MCWError("--brief 和 --draft 需要同时提供")
    brief = load_brief(args.brief)
    facts = extract(brief)
    text = Path(args.draft).read_text(encoding="utf-8")
    card = score_text(text, facts)
    payload = card.to_dict()
    if args.as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        _print_card(payload)
    return 0


def cmd_compare(args: argparse.Namespace) -> int:
    out = Path(args.out)
    left = load_version_files(out, args.run, args.left)
    right = load_version_files(out, args.run, args.right)
    markdown = render_comparison(args.run, left, right)
    destination = run_dir(out, args.run) / f"compare-{args.left}-{args.right}.md"
    destination.write_text(markdown, encoding="utf-8")
    if args.as_json:
        print(
            json.dumps(
                {
                    "run_id": args.run,
                    "left": args.left,
                    "right": args.right,
                    "path": str(destination),
                    "note": OFFLINE_SCORE_NOTE,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print(markdown, end="")
        print(f"wrote: {destination}")
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    history = load_history(Path(args.out), args.run)
    if args.as_json:
        print(json.dumps(history, ensure_ascii=False, indent=2))
        return 0
    print(f"run_id: {history['run_id']}")
    if not history["versions"]:
        print("没有版本")
        return 0
    for item in history["versions"]:
        reviewer = item.get("reviewer") or "—"
        print(
            f"{item['version']} | {item['created_at']} | reviewer {reviewer} | "
            f"approval {item['approval_status']} | overall {item['overall_score']} | {item['comment']}"
        )
    print(f"note: {OFFLINE_SCORE_NOTE}")
    return 0


def cmd_list_runs(args: argparse.Namespace) -> int:
    payload = list_saved_runs(Path(args.out))
    if args.as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    for name in payload["skipped"]:
        print(f"跳过无效运行目录: {name}", file=sys.stderr)
    if not payload["runs"]:
        print("没有运行")
    else:
        for item in payload["runs"]:
            reviewer = item.get("reviewer") or "—"
            comment = item.get("comment") or "—"
            approval = item.get("approval_status") or "—"
            print(
                f"{item['run_id']} | {item['brief_id']} | versions {item['version_count']} | "
                f"{item['latest_version']} | {item['created_at']} | reviewer {reviewer} | "
                f"approval {approval} | overall {item['overall_score']} | {comment}"
            )
    print(f"note: {payload['note']}")
    return 0


def cmd_list_briefs(args: argparse.Namespace) -> int:
    payload = list_briefs(args.directory, channel=args.channel, brief_id=args.brief_id)
    if args.as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    for item in payload["skipped"]:
        print(f"跳过无效 Brief 文件: {item['path']}: {item['error']}", file=sys.stderr)
    if not payload["briefs"]:
        print("没有 Brief")
        return 0
    for item in payload["briefs"]:
        print(
            f"{item['id']} | {item['title']} | {item['channel_label']} | "
            f"卖点 {item['selling_points']} | 必含 {item['must_include']} | "
            f"禁称 {item['forbidden_claims']} | {item['path']}"
        )
    print(f"briefs: {payload['brief_count']}")
    if payload["channels"]:
        parts = ", ".join(
            f"{row['channel_label']} {row['brief_count']}" for row in payload["channels"]
        )
        print(f"channels: {parts}")
    return 0


def cmd_stats(args: argparse.Namespace) -> int:
    payload = summarize_saved_runs(Path(args.out))
    if args.as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    for name in payload["skipped"]:
        print(f"跳过无效运行目录: {name}", file=sys.stderr)
    if payload["run_count"] == 0:
        print("没有运行")
        print(f"note: {payload['note']}")
        return 0
    print(f"runs: {payload['run_count']}")
    print(f"versions: {payload['version_count']}")
    print("approval: " + _join_groups(payload["approval_groups"], "status"))
    print("briefs: " + _join_groups(payload["briefs"], "brief_id"))
    print("backends: " + _join_groups(payload["backends"], "backend"))
    print("channels: " + _join_groups(payload["channels"], "channel_label"))
    overall = payload["overall_scores"]
    if overall["count"] == 0:
        print("overall: count 0")
    else:
        print(
            f"overall: count {overall['count']}, min {overall['min']}, "
            f"max {overall['max']}, mean {overall['mean']}"
        )
    labels = dict(DIMENSIONS)
    parts = [
        f"{labels[key]} {payload['dimension_scores'][key]['mean']}"
        for key, _label in DIMENSIONS
        if key in payload["dimension_scores"]
    ]
    if parts:
        print("dimensions: " + ", ".join(parts))
    print(f"note: {payload['note']}")
    return 0


def cmd_failures(args: argparse.Namespace) -> int:
    payload = inventory_failures(Path(args.out), run_id=args.run, version=args.version)
    if args.as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    for name in payload["skipped"]:
        print(f"跳过无效运行目录: {name}", file=sys.stderr)
    if not payload["failures"]:
        print("没有未满分或被驳回的运行")
    else:
        for item in payload["failures"]:
            _print_failure(item)
    print(f"note: {payload['note']}")
    return 0


def cmd_list_findings(args: argparse.Namespace) -> int:
    payload = inventory_findings(
        Path(args.out),
        run_id=args.run,
        version=args.version,
        rule=args.rule,
        severity=args.severity,
        channel=args.channel,
        draft=args.draft,
        brief=args.brief_id,
    )
    if args.as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    for name in payload["skipped"]:
        print(f"跳过无效运行目录: {name}", file=sys.stderr)
    if not payload["findings"]:
        print("没有发现")
    else:
        for item in payload["findings"]:
            print(
                f"{_cell(item.get('run_id'))} | {_cell(item.get('brief_id'))} | "
                f"{_cell(item.get('version'))} | {_cell(item.get('draft_id'))} | "
                f"{_cell(item.get('rule_id'))} | {_cell(item.get('severity'))} | "
                f"{_cell(item.get('evidence'))}"
            )
    print(f"runs: {payload['n']}")
    print(f"with_findings: {payload['n_with_findings']}")
    print(f"without_findings: {payload['n_without_findings']}")
    print(f"listed: {payload['n_listed']}")
    print("by_rule: " + _format_breakdown(payload["by_rule"], "rule_id"))
    print("by_severity: " + _format_breakdown(payload["by_severity"], "severity"))
    print(f"note: {payload['note']}")
    return 0


def cmd_list_drafts(args: argparse.Namespace) -> int:
    payload = inventory_drafts(
        Path(args.out),
        run_id=args.run,
        version=args.version,
        draft=args.draft,
        variant=args.variant,
        channel=args.channel,
        brief=args.brief_id,
    )
    if args.as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    for name in payload["skipped"]:
        print(f"跳过无效运行目录: {name}", file=sys.stderr)
    if not payload["drafts"]:
        print("没有文案")
    else:
        for item in payload["drafts"]:
            print(_format_draft_row(item))
    print(f"runs: {payload['n']}")
    print(f"with_drafts: {payload['n_with_drafts']}")
    print(f"without_drafts: {payload['n_without_drafts']}")
    print(f"listed: {payload['n_listed']}")
    print(f"recommended: {payload['n_recommended']}")
    print(f"not_recommended: {payload['n_not_recommended']}")
    print("by_brief: " + _format_breakdown(payload["by_brief"], "brief_id"))
    print("by_channel: " + _format_breakdown(payload["by_channel"], "channel"))
    print("by_variant: " + _format_breakdown(payload["by_variant"], "variant"))
    print(f"note: {payload['note']}")
    return 0


def _format_draft_row(item: dict) -> str:
    marker = "recommended" if item.get("recommended") else "—"
    return (
        f"{_cell(item.get('run_id'))} | {_cell(item.get('brief_id'))} | "
        f"{_cell(item.get('version'))} | {_cell(item.get('draft_id'))} | "
        f"{_cell(item.get('variant'))} | {_cell(item.get('angle'))} | "
        f"chars {_number_cell(item.get('char_count'))} | "
        f"overall {_number_cell(item.get('overall'))} | "
        f"{marker} | checklist {_checklist_cell(item.get('checklist_passed'))} | "
        f"high {_number_cell(item.get('high_finding_count'))}"
    )


def _number_cell(value: object) -> str:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return "—"
    if isinstance(value, float) and (value != value or value in (float("inf"), float("-inf"))):
        return "—"
    return str(value)


def _checklist_cell(value: object) -> str:
    if value is True:
        return "passed"
    if value is False:
        return "failed"
    return "—"


def _cell(value: object) -> str:
    if isinstance(value, str) and value:
        return value
    return "—"


def _format_breakdown(rows: list[dict], key: str) -> str:
    if not rows:
        return "—"
    return ", ".join(f"{row[key]} {row['count']}" for row in rows)


def _print_failure(item: dict) -> None:
    approval = item.get("approval_status") or "—"
    best = item.get("best_draft_id") or "—"
    print(
        f"{item['run_id']} | {item['brief_id']} | {item['version']} | "
        f"approval {approval} | best {best} | overall {item['overall_score']}"
    )
    weak = item["weak_dimensions"]
    if weak:
        parts = ", ".join(f"{row['label']} {row['score']}" for row in weak)
        print(f"dimensions: {parts}")
    if item.get("checklist_passed") is False:
        print("checklist: failed")
    for finding in item["high_findings"]:
        rule_id = finding.get("rule_id") or "—"
        message = finding.get("message") or "—"
        evidence = finding.get("evidence") or "—"
        print(f"high: {rule_id} | {message} | {evidence}")
    others = [row for row in item["variant_scores"] if not row.get("recommended")]
    if others:
        parts = ", ".join(
            f"{row.get('variant') or '—'} {row.get('draft_id') or '—'} {row.get('overall')}"
            for row in others
        )
        print(f"variants: {parts}")


def _stored_score_suffix(overall: dict) -> str:
    count = overall["count"]
    if count == 0:
        return ""
    if count == 1 or overall["min"] == overall["max"]:
        return f" mean {overall['mean']}"
    return f" min {overall['min']}, max {overall['max']}, mean {overall['mean']}"


def _join_groups(rows: list[dict], label_key: str) -> str:
    return ", ".join(
        f"{row[label_key]} {row['run_count']}{_stored_score_suffix(row['overall_scores'])}"
        for row in rows
    )


def _score_fixtures(as_json: bool) -> int:
    rows = score_cases()
    failed = [row for row in rows if not row["matched"]]
    if as_json:
        print(json.dumps({"note": OFFLINE_SCORE_NOTE, "cases": rows}, ensure_ascii=False, indent=2))
    else:
        print(f"note: {OFFLINE_SCORE_NOTE}")
        for row in rows:
            actual = row["actual"]
            status = "ok" if row["matched"] else "DIFF"
            print(
                f"{row['id']} | 卖点准确 {actual['selling_point_accuracy']} | "
                f"渠道适配 {actual['channel_fit']} | 合规 {actual['compliance']} | "
                f"可读性 {actual['readability']} | 总分 {actual['overall']} | {status}"
            )
        if failed:
            print(f"{len(failed)} 个用例与记录分数不一致", file=sys.stderr)
    return 1 if failed else 0


def _generator(args: argparse.Namespace):
    if args.mock:
        return MockGenerator()
    api_key = os.environ.get("MCW_LLM_API_KEY", "").strip()
    if not api_key:
        raise MCWError("未设置 MCW_LLM_API_KEY。离线运行请加 --mock。")
    base_url = args.base_url or os.environ.get("MCW_LLM_BASE_URL", DEFAULT_BASE_URL)
    model = args.model or os.environ.get("MCW_LLM_MODEL", DEFAULT_MODEL)
    return OpenAICompatGenerator(api_key=api_key, base_url=base_url, model=model)


def _print_run(result: RunResult, directory: Path, as_json: bool) -> None:
    rows = []
    for draft, checklist, score in zip(result.drafts, result.checklists, result.scores):
        highs = sum(1 for item in checklist.findings if item.severity == "high")
        rows.append(
            {
                "variant": draft.variant,
                "angle": draft.angle,
                "chars": draft.char_count,
                "overall": score.overall,
                "dimensions": score.dimension_map(),
                "high_risks": highs,
                "passed": checklist.passed,
            }
        )
    summary = {
        "run_id": result.run_id,
        "version": result.version,
        "backend": result.backend,
        "brief_id": result.brief.id,
        "artifacts": str(directory),
        "approval": result.approval.status,
        "best_draft_id": result.best_draft_id,
        "variants": rows,
        "note": OFFLINE_SCORE_NOTE,
    }
    if as_json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return
    print(f"run_id: {result.run_id}")
    print(f"version: {result.version}")
    print(f"backend: {result.backend}")
    print(f"brief: {result.brief.title} ({result.brief.id})")
    print(f"artifacts: {directory}")
    print(f"approval: {result.approval.status}")
    for row in rows:
        print(
            f"{row['variant']} | {row['angle']} | chars {row['chars']} | "
            f"overall {row['overall']} | high {row['high_risks']}"
        )
    print(f"best: {result.best_draft_id}")
    print(f"note: {OFFLINE_SCORE_NOTE}")


def _print_card(payload: dict) -> None:
    for key, label in DIMENSIONS:
        print(f"{label}: {payload['dimensions'][key]['score']}")
    print(f"总分: {payload['overall']}")
    print(f"note: {payload['note']}")


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
