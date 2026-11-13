"""Command line: mcw run | score | compare | list-versions | list-runs."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from mcw import __version__
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
    list_saved_runs,
    load_history,
    load_version_files,
    make_run_id,
    persist_run,
    prepare_version,
    rescore_version,
    run_dir,
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
