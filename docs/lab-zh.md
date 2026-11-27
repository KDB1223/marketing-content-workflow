# 实验：离线内容分

这篇手册用仓库里的中文 Brief 走完一条流水线，并把量表拆开。做完以后应该能回答三件事：事实清单从哪来，风险项为什么出现，总分为什么不能拿去汇报转化。

## 0. 安装

需要 Python 3.10 及以上。

```bash
python3 -m pip install -e ".[dev]"
pytest -q
```

`pytest` 不读取 API key。CI 同样只跑离线路径。

## 1. 读一份 Brief

打开 `briefs/creditcard-official.yaml`。结构化字段是这份文案的合同：

- `product.selling_points`：允许写进正文的事实原句
- `product.disclaimers`：必须能在成稿里找到的声明
- `audience`：受众、痛点和语气
- `channel`：渠道、体裁、字数上限；不写 `required_elements` 时使用该渠道的默认组件
- `conversion`：转化目标和行动号召原句
- `constraints`：必含、禁用词、禁用宣称、合规备注

`channel.name` 接受 `官网`、`小红书`、`抖音`、`微信公众号`、`电商详情`、`微博`，也会接受对应的英文 id。

`python3 -m mcw list-briefs` 清点目录里的 Brief（默认 `briefs/`）。它只看该目录的直接子文件，后缀是 `.yaml`、`.yml` 或 `.json`，并用现有的 `load_brief` 校验。文本模式每行是 id、标题、渠道名，以及卖点、必含、禁称的条数。校验失败的文件不会让整条命令失败，stderr 会写 `跳过无效 Brief 文件`。它不调用模型，也不写入 `.mcw/runs`。条数是字段里有几句话，不是离线内容分，也不是转化率。`--channel` 接受规范渠道 id、中文渠道名，或 `CHANNEL_ALIASES` 里的别名（例如 `xhs`、`微信`）；`--id` 精确匹配 Brief.id。筛完没有命中时打印 `没有 Brief`，退出码仍是 0。

提取阶段不做摘要模型。`src/mcw/stages/extract.py` 把这些字段投影成 `fact_lines`。生成器拿到的是这份清单，不是原始 YAML 的任意注释。

## 2. 跑通 Mock

```bash
python3 -m mcw run briefs/sunscreen-xhs.yaml --mock --run-id lab-sunscreen
```

查看：

```text
.mcw/runs/lab-sunscreen/extracted.json
.mcw/runs/lab-sunscreen/drafts.json
.mcw/runs/lab-sunscreen/checklist.json
.mcw/runs/lab-sunscreen/scores.json
.mcw/runs/lab-sunscreen/prompts.json
.mcw/runs/lab-sunscreen/approval.json
.mcw/runs/lab-sunscreen/report.md
.mcw/runs/lab-sunscreen/versions/v1/
```

根目录上的 JSON 和 Markdown 是最新版。`versions/v1/` 保留这一版的快照。`prompts.json` 里的 `template_id` 是 `prompt-template-v1`，系统提示词要求模型不得新增功效，并禁止绝对化用语。Mock 不请求该提示词对应的接口，但档案仍保存同一份模板，方便以后和在线后端对照。

`approval.json` 此时是 `status: pending` 的存根。流水线不会因为还没人点头就停下来；确认是记录，不是闸机。

## 3. 看清单，而不是只看总分

`checklist.json` 的每条 finding 有 `rule_id`、`severity`、`evidence`、`suggestion`。内置规则：

| rule_id | 在查什么 | 进入哪个分数 |
| --- | --- | --- |
| `absolute_words` | 国家级、最佳、全网第一、100% 等；`第一`、`最新` 为中风险 | 合规 |
| `overclaim` | 治愈、医学证明、医院同款等 | 合规 |
| `must_avoid` | Brief 点名禁止的词 | 合规 |
| `forbidden_claim` | Brief 点名禁止的宣称 | 合规 |
| `missing_disclaimer` | 有声明却没有「【声明】」或声明原文 | 合规 |
| `missing_must_include` | 必含信息没出现 | 只进清单；卖点准确另有扣分 |
| `length_limit` | 超过 `max_chars`（不计空白） | 只进清单；渠道适配另扣 30 |
| `required_element` | 标题、正文、话题标签、钩子、声明、卖点等 | 渠道适配，每项 15 |
| `channel_mismatch` | 官网俚语、公众号堆标签、小红书写「阅读原文」等 | 渠道适配，每项 20 |

合规扣分只统计前五行：高 25、中 12、低 5，同一短语在同一条规则里只记一次。渠道问题留在渠道适配，避免一条俚语把合规分和渠道分一起打穿。

两条容易误伤的例外：

- `第一位`、`第一步`、`第一次`、`第一时间` 里的「第一」不记绝对化。溶豆 Brief 的「配料表第一位是生牛乳」会整句进入正文，清单不应因此报警。
- `最近`、`最后`、`最终`、`最为`、`最初` 里的「最」不记。`must_avoid` 写成「最」时同样跳过这些词。`最好` 仍会命中。

抖音默认组件包含「钩子」：首行 4–28 个字符。电商详情会检查产品名是否出现。

## 4. 复放量表

```bash
python3 -m mcw score --fixtures
```

七篇稿子冻在 `src/mcw/fixtures/cases.json`。命令把现算结果和 `expect` 逐项比较，不一致则退出码 1。这是 CI 里的可复现检查。

当前记录：

| 用例 | 卖点准确 | 渠道适配 | 合规 | 可读性 | 总分 |
| --- | ---: | ---: | ---: | ---: | ---: |
| clean-xiaohongshu | 100 | 100 | 100 | 100 | 100 |
| absolute-claim | 100 | 100 | 75 | 100 | 94 |
| missing-disclaimer | 100 | 100 | 75 | 100 | 94 |
| official-slang | 100 | 80 | 100 | 100 | 95 |
| partial-selling-point | 33 | 100 | 100 | 100 | 77 |
| missed-selling-points | 0 | 100 | 100 | 100 | 65 |
| dense-sentence | 100 | 100 | 100 | 85 | 98 |

`partial-selling-point` 三条卖点只完整保留第一条，`round_half_up(100 / 3) = 33`。再乘权重 0.35，和其他满分维度一起得到 77。

## 5. 公式

字数一律去掉空白后再数。

**卖点准确。** 卖点原句在去空白、忽略大小写后是文案子串，记命中。否则要求拉丁字母和数字片段（如 `SPF50+`）全部出现，且中文二字片段覆盖率至少 60%。得分是命中比例的四舍五入（0.5 向上），每缺一条 `must_include` 再减 15，最后夹到 0–100。

**渠道适配。** 从 100 起算。超字数减 30，不足 12 字减 20，每个缺失组件减 15，每个 `channel_mismatch` 减 20。

**合规。** 从 100 减去合规规则的罚分。渠道、字数和必含项的 finding 不进这项。

**可读性。** 用 `。！？!?` 分句。平均句长（总字数 / 句数）小于 8 减 20；大于 45 时，超出部分每 10 字减 10，不足 10 字按 10 字计，最多减 40。超过 30 字且没有 `。！？，、` 减 25。超过 80 字且没有换行减 15。中文四字片段出现不少于 5 次减 10。

**总分。**

```text
round_half_up(0.35 * 卖点准确 + 0.25 * 渠道适配 + 0.25 * 合规 + 0.15 * 可读性)
```

演算示例，不是某篇冻结稿：四个维度分别是 100、100、75、90。

```text
0.35*100 + 0.25*100 + 0.25*75 + 0.15*90
= 35 + 25 + 18.75 + 13.5
= 92.25
→ 92
```

`weighted_overall(100, 100, 75, 90)` 在测试里锁着这个结果。

每份 `scores.json` 都带同一句说明：

> 离线内容分只评估文案与 Brief 的一致性、渠道形态、合规风险和可读性。它不是真实投放转化率，也不能代替 A/B 实验或业务结果。

转化要看曝光、点击、申请或成交。那些数字不在 Brief 里，量表也不读取它们。

## 6. 人工确认和版本对照

```bash
python3 -m mcw run briefs/creditcard-official.yaml --mock --run-id lab-card
python3 -m mcw run briefs/creditcard-official.yaml --mock \
  --continue-run lab-card \
  --reviewer 林可 \
  --comment "删掉口头禅，保留审批声明" \
  --approval examples/approval-approved.json
python3 -m mcw list-versions lab-card
python3 -m mcw list-briefs
python3 -m mcw list-runs
python3 -m mcw stats
python3 -m mcw failures
python3 -m mcw list-findings
python3 -m mcw list-drafts
python3 -m mcw show
python3 -m mcw compare lab-card --left v1 --right v2
```

`examples/approval-approved.json` 用变体字母 `A` 选中当前版本的 A 稿。`approved` 或 `rejected` 必须带审阅人和 `draft_id`。备注不是「初稿」时，会写进提示词；Mock 还会在不超字数的前提下加一行「修订回应」。超字数就只把备注留在 `versions.json`，不把正文撑破。

续写时 Brief 的指纹必须和第一版一致。防晒乳不能接着写进咖啡的版本史。

`mcw list-briefs` 不读 `.mcw/runs/`。它清点 Brief 文件本身：渠道、卖点条数、必含条数和禁称条数。没有模型调用，也没有分数。

几次运行叠在一起时，`mcw list-runs` 只读 `.mcw/runs/` 里的 `manifest.json` 和 `versions.json`，按最新版本的时间列出 run id、Brief、版本数、确认状态和离线总分。它不调用模型，也不重算量表。这一列总分仍是离线内容分，不是投放转化率。`--json` 额外带上渠道 id 和渠道名；索引里没有渠道时是 `unknown`。

`mcw stats` 是同一批存档的汇总：按确认状态、Brief、后端和渠道，给出各组已存储离线分的次数、最小、最大和平均。新运行会把渠道 id 和渠道名写进 `manifest.json` 和 `versions.json`。旧索引没有渠道时记为 `unknown`。它同样只读这两个文件，不调用模型，也不重算量表。这些数字仍是离线内容分，不是投放转化率。

`mcw failures` 是同一批存档里需要复核的子集。推荐稿的离线分缺失或低于 100、确认状态是驳回，或推荐稿的清单未通过、含高风险发现时，这条运行会出现。它先读 `manifest.json` 和 `versions.json`，再读该版本已经写好的 `checklist.json` 和 `scores.json`，打印低于 100 的维度和已保存的高风险项（规则 id、说明、证据）。它不调用模型，也不重算量表。防晒乳这种 pending 且 100 分、清单通过的 Mock 运行不会出现；非推荐变体分数更低，只要推荐稿是干净的，也不会单独把这次运行列出来。这些数字仍是离线内容分，不是投放转化率。

`mcw list-findings` 回答的是另一件事：清单里已经记下了哪些发现。它仍是只读，先读 `manifest.json` 和 `versions.json`，再读选中版本的 `checklist.json`，不调用模型，也不重算规则或量表。和 `failures` 的差别是：`failures` 保持运行级，只看推荐稿上的高风险项，外加未满分或被驳回；`list-findings` 是发现级，选中版本里每一份草稿、每一种严重级别都会列出，非推荐稿上的 medium 也会出现。默认仍是每条运行的最新版本。`mcw list-findings <run> [--version v1]` 只看这一条。`--rule`、`--severity`、`--draft`、`--brief`、`--channel` 同时生效。`--channel` 接受规范渠道 id、中文渠道名或 `CHANNEL_ALIASES` 里的别名（例如 `xhs`）；旧索引没有渠道时是 `unknown`，只匹配 `unknown`。没有命中，或清单里本来就没有发现，都打印 `没有发现`，退出码仍是 0。有发现和没有发现的运行数在过滤之前就算好，过滤只改变列出的行，以及按规则、按严重级别的计数。这些行来自已保存的清单，不是投放转化率。

`mcw list-drafts` 回答的是文案本身：选中版本里保存了哪些变体。它仍是只读，先读 `manifest.json` 和 `versions.json`，再读该版本的 `drafts.json`，按文件顺序列出每一份草稿，不限于 `best_draft_id`。`scores.json` 和 `checklist.json` 能读到时，按草稿 id 拼上已保存的离线分、清单是否通过，以及高风险条数。这两个文件缺失或读不出来时，草稿行还在，对应字段留空。`drafts.json` 没有可用列表时，改用 `scores.json` 里的草稿列表，再退到版本索引上的 `variant_scores`。它不调用模型，不重算量表，也不重跑风险规则。默认仍是每条运行的最新版本。`mcw list-drafts <run> [--version v1]` 只看这一条。`--draft`、`--variant`、`--brief`、`--channel` 同时生效。`--channel` 接受规范渠道 id、中文渠道名或 `CHANNEL_ALIASES` 里的别名（例如 `xhs`）；旧索引没有渠道时是 `unknown`，只匹配 `unknown`。没有命中，或版本里本来就没有文案，都打印 `没有文案`，退出码仍是 0。有文案和没有文案的运行数在过滤之前就算好。这些数字是已保存的离线内容分，不是投放转化率。

跑完 Mock 之后，`mcw show lab-sunscreen` 打印已经保存的正文，并带上已保存的维度分、清单发现和确认状态。它只读 `drafts.json` 里的 text，不调用模型，不重算量表，也不重跑风险规则。没有正文的回退行会留空，不会编一句文案。这些分数仍是离线内容分，不是投放转化率。

对照 Markdown 含审阅备注、推荐变体各维加减分、按变体的 unified diff，以及消除或新出现的检查项。开头重复离线分说明，避免把 `+0` 读成「转化没变」或把 `-6` 读成「少卖了 6%」。

## 7. 加一条规则

CLI 使用 `builtin_rules()`。Python API 可以追加规则，清单会多出一行；默认总分仍只认识内置规则 id。

```python
from mcw.models import Finding
from mcw.risk.rules import builtin_rules, run_rules

class CompetitorNameRule:
    id = "competitor_name"

    def check(self, text, facts):
        if "竞品甲" in text:
            return [
                Finding(
                    rule_id=self.id,
                    severity="medium",
                    message="出现了事实清单之外的竞品名。",
                    evidence="竞品甲",
                    suggestion="删掉竞品名，除非 Brief 明确允许比较。",
                )
            ]
        return []

findings = run_rules(text, facts, rules=[*builtin_rules(), CompetitorNameRule()])
```

若希望新规则影响合规分或渠道分，在 `src/mcw/scoring/rubric.py` 里显式决定它属于哪一项，并给 `tests/` 加一条锁定罚分的用例。不要让同一条 finding 在两个维度各扣一次，除非实验手册也这样写。

## 8. 换一篇自己的 Brief

复制 `briefs/sunscreen-xhs.yaml`，改 id、卖点和声明。写完可以用 `python3 -m mcw list-briefs` 看这份 Brief 有没有被收进 `briefs/`，渠道名是否识别，卖点和禁称各有几条。然后：

```bash
python3 -m mcw run briefs/your-brief.yaml --mock --run-id your-demo
python3 -m mcw score --run your-demo
```

卖点尽量写成能原句出现的事实。痛点里如果夹着「最」或「第一」，Mock 会把痛点写进标题，清单就会报警。那是规则在工作，不是生成器随机发挥。

在线后端：

```bash
export MCW_LLM_API_KEY=sk-...
export MCW_LLM_BASE_URL=https://api.openai.com/v1
export MCW_LLM_MODEL=gpt-4o-mini
python3 -m mcw run briefs/your-brief.yaml --run-id your-live
```

模型被要求只输出 JSON：`{"drafts":[{"angle","title","body"}]}`。解析失败会退出码 2，并且不会把密钥写进档案。生成完仍然用同一套离线量表打分。

这套工具不提供法律意见。绝对化用语和疗效词是编辑清单，最终能不能发，仍由负责该渠道的人确认。
