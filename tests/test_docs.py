from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_docs_name_the_commands_and_the_offline_boundary() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    chinese = (ROOT / "README.zh-CN.md").read_text(encoding="utf-8")
    lab = (ROOT / "docs" / "lab-zh.md").read_text(encoding="utf-8")
    for text in (readme, chinese, lab):
        assert "mcw run" in text
        assert "mcw score" in text
        assert "mcw compare" in text
        assert "mcw list-versions" in text
        assert "```mermaid" in text or "round_half_up" in text
        assert "离线内容分" in text
    assert "clean-xiaohongshu" in readme
    assert "| 100 | 100 | 75 | 100 | 94 |" in readme
    assert "| 100 | 80 | 100 | 100 | 95 |" in chinese
    assert "92.25" in lab
    assert (ROOT / "LICENSE").read_text(encoding="utf-8").startswith("MIT License")
    assert (ROOT / "CONTRIBUTING.md").exists()
