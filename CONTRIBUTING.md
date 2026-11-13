# Contributing

Issues and pull requests are welcome. The useful change is one that keeps the pipeline auditable and the offline numbers reproducible.

## Setup

```bash
python3 -m pip install -e ".[dev]"
pytest -q
```

Python 3.10 or newer. Tests and `mcw score --fixtures` must pass without `MCW_LLM_API_KEY`.

## What to keep stable

- `extract` stays a deterministic projection of the Brief. Do not call a model inside it.
- Generators receive `ExtractedFacts`, not the raw YAML mapping.
- Risk-rule ids used by the rubric stay in `COMPLIANCE_RULES` or in the channel-fit counters. A new finding should not change two dimension scores unless `docs/lab-zh.md` says so.
- Fixture totals in `src/mcw/fixtures/cases.json` are a contract. If you change the rubric on purpose, update `expect`, the score tables in both READMEs, and the lab in the same change.
- The sentence stored as `OFFLINE_SCORE_NOTE` stays on score JSON, the Markdown report, and compare output.

## Add a Brief

1. Copy `briefs/sunscreen-xhs.yaml` or `briefs/kidsnack-ecommerce.json`.
2. Use a new `id`. Keep selling points literal, and keep risky words out of `pain_points` unless you want the checklist to fire.
3. Run `python3 -m mcw run briefs/<file> --mock --run-id <id>` and read `checklist.json`. `python3 -m mcw list-runs` lists every saved run under `.mcw/runs/` (latest version, approval, stored offline score) without calling a model.

Channel names can be Chinese (`小红书`, `抖音`, `微信公众号`, `官网`, `电商详情`, `微博`) or the English ids in `mcw.schema.CHANNEL_ALIASES`.

## Add a risk rule

Subclass is unnecessary. An object with `id` and `check(self, text, facts)` is enough. Follow the example in `docs/lab-zh.md`. Cover it with a unit test that asserts `rule_id`, `severity`, and `evidence`.

`第一位` / `第一时间` and `最近` / `最后` are intentional exceptions. Do not flag them as superlatives.

## Score changes

`mcw score --fixtures` exits 1 when a recorded number moves. Update the fixture `expect` values by rescoring, then update:

- `README.md`
- `README.zh-CN.md`
- `docs/lab-zh.md`

Include a test that pins any new penalty so the next change cannot drift silently.

## Commits

Prefer a short message that says what changed for a reviewer, for example `Score channel slang only in channel fit`. Do not commit `.mcw/` run output or API keys.

## License

By contributing you agree that your changes are released under the [MIT License](LICENSE).
