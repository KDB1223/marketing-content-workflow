from __future__ import annotations

import json
from pathlib import Path

import pytest

from mcw.briefs_inventory import list_briefs
from mcw.errors import MCWError


def _brief(brief_id: str, channel: str) -> str:
    return f"""id: {brief_id}
title: 标题{brief_id}
locale: zh-CN
product:
  name: 产品
  category: 类
  selling_points:
    - 卖点甲
audience:
  segment: 人群
  tone: 平静
channel:
  name: {channel}
  format: note
  max_chars: 100
conversion:
  goal: 目标
  cta: 行动
"""


def _brief_json(brief_id: str, channel: str) -> str:
    return json.dumps(
        {
            "id": brief_id,
            "title": f"标题{brief_id}",
            "locale": "zh-CN",
            "product": {"name": "产品", "category": "类", "selling_points": ["卖点甲"]},
            "audience": {"segment": "人群", "tone": "平静"},
            "channel": {"name": channel, "format": "note", "max_chars": 100},
            "conversion": {"goal": "目标", "cta": "行动"},
        },
        ensure_ascii=False,
    )


def test_sorts_by_filename_and_ranks_channels(tmp_path: Path) -> None:
    folder = tmp_path / "briefs"
    folder.mkdir()
    (folder / "z-douyin.yaml").write_text(_brief("late", "抖音"), encoding="utf-8")
    (folder / "a-douyin.yaml").write_text(_brief("early", "douyin"), encoding="utf-8")
    (folder / "m-wechat.YML").write_text(_brief("mid", "微信"), encoding="utf-8")
    (folder / "m-xhs.JSON").write_text(_brief_json("snack", "xhs"), encoding="utf-8")
    (folder / ".hidden.yaml").write_text(_brief("hidden", "微博"), encoding="utf-8")
    (folder / "notes.txt").write_text("ignore", encoding="utf-8")
    nested = folder / "nested"
    nested.mkdir()
    (nested / "inside.yaml").write_text(_brief("inside", "官网"), encoding="utf-8")

    payload = list_briefs(folder)
    assert [row["id"] for row in payload["briefs"]] == ["early", "mid", "snack", "late"]
    assert [row["path"] for row in payload["briefs"]] == [
        (folder / name).as_posix()
        for name in ("a-douyin.yaml", "m-wechat.YML", "m-xhs.JSON", "z-douyin.yaml")
    ]
    assert [(row["channel"], row["brief_count"]) for row in payload["channels"]] == [
        ("douyin", 2),
        ("wechat", 1),
        ("xiaohongshu", 1),
    ]
    assert payload["skipped"] == []
    assert payload["directory"] == folder.as_posix()
    assert all(isinstance(row["must_include"], int) for row in payload["briefs"])


def test_skipped_files_stay_visible_when_filters_match_nothing(tmp_path: Path) -> None:
    folder = tmp_path / "briefs"
    folder.mkdir()
    (folder / "ok.yaml").write_text(_brief("ok-brief", "小红书"), encoding="utf-8")
    (folder / "bad.yaml").write_text("id: [\n", encoding="utf-8")

    payload = list_briefs(folder, channel="wechat", brief_id="ok-brief")
    assert payload["briefs"] == []
    assert payload["brief_count"] == 0
    assert payload["channels"] == []
    assert len(payload["skipped"]) == 1
    assert payload["skipped"][0]["path"].endswith("/bad.yaml")
    assert "无法解析" in payload["skipped"][0]["error"]

    unmatched = list_briefs(folder, channel="not-a-channel")
    assert unmatched["brief_count"] == 0
    assert len(unmatched["skipped"]) == 1


def test_missing_directory_raises(tmp_path: Path) -> None:
    missing = tmp_path / "nope"
    with pytest.raises(MCWError, match="找不到 Brief 目录"):
        list_briefs(missing)
    a_file = tmp_path / "file.yaml"
    a_file.write_text("id: x\n", encoding="utf-8")
    with pytest.raises(MCWError, match="找不到 Brief 目录"):
        list_briefs(a_file)
