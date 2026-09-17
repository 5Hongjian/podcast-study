# 从合格原文到阅读内容

输入是已通过输入检查的文字稿包。阅读顺序为全文总结、思维导图、问答、用户思考；先验收底稿，导图直接呈现该底稿，再写问答与总结、验收、交付。用户笔记由网站独立保存，生成内容不得包含或覆盖它们。代码只校验结构和已记录的评估，不证明语义正确。

## 两次内容检查

1. 通读原文，建立下面的 `nodes`、`citations`、`coverage`。长节目按连续片段处理并保留相邻上下文，再统一主题；每段归入主题或记录省略原因。同一主题多次出现分别保留位置，不制造连续时间范围。
2. 先运行 `check_content.py --stage outline` 修复结构问题并取得 digests；缺评估的 `needs_review` 只允许进入审阅，不能进入正文生成。独立评估先阅读原文、列出重要观点，再对照底稿，将真实判断写入 review 的 `outline`，带评估重跑为 `ready` 才继续。
3. 图状导图与文字大纲直接呈现通过验收的同一份 `nodes`，不重新抽取层级。问答选择值得解释的问题，再写覆盖全期的总结；简单背景无需强行另设问答。无原文依据的解释不得归给嘉宾，原节目未展开原因就如实说明；整理者示例和 AI 推导明确标注。每个正文块按具体断言选择引用，不能只沿用主题代表段；“这／上述条件／后来补充”等回指要带实际条件、例子或方法的原句。总结压缩后仍核对相邻引用能否支持全部重要陈述。
4. 成品先运行程序结构检查，再独立评估全文与输出的两个方向：输出逐项回查原文，原文的重要内容回查输出。将真实判断写入 `final`，带评估重跑。代码失败修结构或引用，语义遗漏修底稿，含义错误修正文及关联呈现；评估失效范围见下文。
5. 最多两轮有依据的局部修订，仍有重要问题保留草稿与具体原因。脚本不调用模型或自动计数重试，宿主记录实际轮数，不能把“通过”复制到新稿。

## 必须通过的内容标准

| 检查 | 通过要求 | 退回例子 |
|---|---|---|
| `faithfulness` | 核心意思、语气、条件和说话归属符合原文 | 将“可能、限于特定条件”写成“一定、普遍成立” |
| `coverage` | 主要议题及影响理解的分歧、反例在相应输出中体现 | 每句都有依据，却遗漏整段主要论题 |
| `structure` | 一级主题、二级主要论点、三级依据或条件；关系由原文支持 | 把支撑性的例子抬成核心结论，或按固定时长划主题 |
| `attribution` | 节目观点、整理者示例、AI 推导分开；无虚构用户想法 | 新增解释被写成嘉宾原话 |
| `consistency` | 总结、导图和问答的结论与前提一致 | 问答已加回限制，总结仍保留绝对结论 |
| `citation_support` | 相邻引用确实支持所述含义，并保留必要上下文 | 引用能定位，但原话不支持回答的断言 |

outline 检查前三项；final 全部检查。状态为 `passed/failed/uncertain`，每项必须写实际依据。缺失、存疑、重要错误未解决都不能通过，表达优美不能抵消内容错误。代码校验所有引用摘录、ID、层级关系、覆盖映射和版本，语义由独立评估判断。

总结与导图须覆盖全部主要主题，问答不必逐主题重复。final 的 coverage/understanding 仍检查重要推理、分歧、反例及后置限制在适合的正文或节点详情中得到充分解释；只列一个节点标题不算覆盖。问题范围缩小不能降低这两项标准，不能以“未选为问题”省略重要内容。

## 阅读质量评分

| quality 字段 | 0：不可用 | 1：需明显修改 | 2：可交付 | 3：良好 |
|---|---|---|---|---|
| `overview` | 不知讨论什么 | 零散观点、主次不清 | 核心问题和主要观点清楚 | 主题关系及重要分歧也清楚 |
| `understanding` | 答非所问或错误 | 只复述结论 | 解释原文给出的理由、案例与边界 | 推理关系清楚，明确哪些原文未解释 |
| `organization` | 无法导航 | 分类重复、论点案例混杂 | 层级合理、标题有实质内容 | 扫描即可理解结构并选择深入位置 |
| `concision` | 冗余掩盖重点或压缩失真 | 重复、空泛、篇幅失衡 | 有取舍且必要上下文保留 | 各部分各有作用，展开增加理解 |

四项均至少 2 分，每项给理由，不取平均分抵消短板。这是初版门槛，应使用人工校准样例验证；不能用长度、关键词命中或模型信心代替判断。

## 内容 JSON 契约（schema_version 1）

所有 ID 是 1–100 位英文字母、数字、下划线或连字符；内容中各输出 ID 跨区块唯一。原文偏移沿用 Unicode 码点、左闭右开。完整契约由随附脚本检查，字段如下：

- `episode`：`id`、`title`；可选 `subtitle` 和 `demo`（只有演示内容为 true）。
- `source`：文字稿包中的 `source_version_id`、`transcript_sha256`。可附 `url`（已核对的 http/https 节目原页）、`label`（来源名称）、`reading_note`（面向读者的来源和限制说明）；网页呈现原页链接，限制说明须与输入评估一致，不冒充音频核验。
- `citations`：`{id, number, segment_id, start, end, quote}`；number 是唯一的正整数显示编号（不超过 1000000）。同一来源范围复用 ID 与编号；局部更新保留既有编号，新增引用追加编号，不按页面排序重编。
- `nodes`：`{id, parent_id, level, kind, title, text, citation_ids}`。一级 `topic`，二级 `claim`，三级 `reason/example/condition/explanation`；根的 parent_id 为 null。text 解释节点含义和必要条件。不要为填字段臆造解释。
- `coverage`：每个原文段落一个 `{segment_id, disposition, topic_ids, reason}`；covered 必须指向确有该段依据的一级主题，omitted 的 topic_ids 为空且必须给理由。登记不等于已理解，独立评估仍须核对。
- `summary`：若干 `{id, title, text, attribution, claim_ids, citation_ids}`；claim_ids 指向二级论点，覆盖所有主要主题。
- `questions`：非空数组 `{id, question, topic_ids, answer}`；answer 是 `{id, text, attribution, claim_ids, citation_ids}` 数组。topic_ids 必须等于答案 claim_ids 对应的主题，可由这些论点的父节点计算；不要求问答覆盖所有主题。问题本身不能偷换结论。attribution 只允许 `source/ai_inference/editor_example`，前两类必须有依据。

outline 阶段可省略 summary/questions。个人笔记不属于此 JSON。网站从一个完整包读取三种呈现，禁止单独替换半份内容。

## 评估记录与调用

评估文件为 `{ "outline": {...}, "final": {...} }`。首次运行返回当前 digests；每个评估对象必须有：

- `content_sha256`：outline 使用 digests.outline，final 使用 digests.final；`transcript_package_sha256` 使用 digests.transcript_package。outline 绑定节目、来源、nodes、coverage 及节点实际使用的引用；final 绑定全部内容。只新增/修改/删除回答或总结专用引用时，结构检查和 final 必须重做，未受影响的新式 outline 评估可复用；节点、覆盖、底稿引用或来源变化仍须重评 outline。旧式包含全引用的 outline 指纹只有与当前完整底稿及源包仍匹配时才接受，不改写旧记录；否则重评，不能只换哈希继承通过。
- `method`：`independent_call/human/separate_review`，记录实际方式。
- `reviewed_segment_ids`：实际读过的全部原文段 ID。不能仅检查生成者选择的引用。
- `checks`：上述阶段的检查项，每项 `{status, evidence}`；evidence 说明核对位置、范围与依据。
- `essential_points`：评估者从原文独立提出的 `{text, segment_ids, output_ids, status, reason}` 数组；status 为 covered/missing/uncertain，缺漏或不确定不能通过。outline 的 output_ids 指向节点，final 可指向节点、总结块、问题或回答块。
- `issues`：`{severity, status, output_ids, segment_ids, reason, resolution}`；severity 为 major/minor，status 为 open/resolved，解决后须填修复依据。重要问题写清原文、输出差异、影响范围与修改方向，不接受只有“再深入一点”的空泛反馈。
- final 另有 `quality`：上述四项各填 `{score: 0..3, reason}`。

从技能目录执行：

```bash
python3 scripts/check_content.py /path/to/content.json --transcript /path/to/transcript-package.json --stage outline --review /path/to/content-review.json
python3 scripts/check_content.py /path/to/content.json --transcript /path/to/transcript-package.json --review /path/to/content-review.json
```

退出码 0 对应 ready，1 对应 needs_review，2 对应 blocked。宿主保存实际报告、评估和轮数，不手填更高状态。只有 final ready 才能加 `--publish /path/to/site/dist/episode.json` 原子写入网站数据；未通过或写入失败保留旧版。该参数只替换本地数据，实际网站保存、构建及部署按该网站工具执行。

发布包保留全文、原文引用和渲染必需的数据，不带内部评估意见或用户笔记。原始时间字段不等于已核验：只有输入 timing 检查通过且包含合法依据和证据时，发布包才保留 cue/segment_start 导航精度；否则保留原始时间数据但按原句定位，并说明限制。恢复先核对已有部署，避免重复发布；网页核验按以下范围执行。

## 页面核验范围

每次发布都核对实际版本与完整数据，运行网站数据校验，并在实际页面检查原文可读、首尾及跨段代表引用、代表性导图分支、笔记保存后刷新可读及当前原文版本对应。已有笔记不得因内容更新而被覆盖；没有浏览器能力时保留未验收状态，不把数据校验当作页面通过。

- **仅更新内容**：只有页面组件、样式、构建/部署配置和笔记存储契约与有记录的已验收版本一致，且本次内容在已测长度、节点数量和布局类型范围内，才可复用该版本的完整交互回归；本次实际页面检查仍必须执行。
- **首次发布、代码/配置变化、既有故障或范围不明**：执行完整回归，覆盖数字引用、图文切换、累计层级、缩放/拖动/适配、原文栏隐藏和位置保留、草稿及笔记刷新保留、同源重新生成不改笔记和来源变更隔离。
- **超长原文、超大导图、长标题或新字符/布局边界**：在本次检查上追加受影响的容量与布局测试；范围不能判断时按完整回归处理，不因“模板没改”跳过内容造成的故障。

在任务的 `stage_results.verify` 记录本次实际检查范围、复用依据（模板/部署基线和证据位置）、内容边界及结果；无旧证据时不默认已测。页面与笔记核验通过后交付链接，归档与清理按 [任务记录规则](task-state.md) 继续，清理失败不改变已交付事实。

## 校准与回归

选择少量有代表性的节目，人工标注必须覆盖的观点、不可误读的条件及易错位置，无需唯一标准文章。将重要错误漏报、有效改写误判及偏好长文的问题用于校准；保留一部分样例只用于回归。更换模型、提示词或结构后，对固定输入重复生成三次，分别记录首轮与修订后结果，不挑最好的一次。三次是初筛，不是可靠率证明。合成测试验证程序拒绝错误输入，不能证明真实节目理解质量。
