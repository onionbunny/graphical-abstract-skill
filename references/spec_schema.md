# figure_spec.json 数据契约（spec_version 1.0）

LLM 从科研材料中抽取信息后，必须写成符合本契约的 JSON。渲染器只接受本契约，
不允许在渲染阶段临时发明字段。所有坐标由渲染器确定性计算，spec 中只写逻辑位置（grid/slot）。

## 顶层字段

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| spec_version | str | 是 | 固定 "1.0" |
| case_id | str | 是 | 来自 /input/case.json，原样复制 |
| title | str | 是 | 图题，≤60 字符，来自材料标题或凝练 |
| canvas | obj | 否 | {width_mm:180, height_mm:120, dpi:300}；期刊单页横版默认值 |
| panels | list | 是 | 面板，见下 |
| entities | list | 是 | 科学实体，见下 |
| relations | list | 是 | 实体间关系（可为空列表，但机制类案例不应为空） |
| charts | list | 否 | 数据图（有定量结果时必填） |
| groups | obj | 有 charts 或是 | 分组→颜色映射，见下 |
| conclusion | obj | 是 | {text, source}，结论一句话，≤120 字符 |
| uncertainties | list | 是 | 可为空；每条 {item, reason, handling} |
| off_figure_notes | list | 否 | 只能进图注/不能上图的信息（样本量细节、统计方法等） |

## source 对象（溯源，强制）

每个 entity / relation / chart / conclusion 必须带：

```json
"source": {"file": "materials/paper.pdf", "locator": "p.4, Fig.2 caption", "quote": "原文逐字片段（≤200字符）"}
```

- file：相对 /input 的真实路径；locator：页码/章节/行号/表名；quote：支持该元素的最小原文片段。
- 图中的任何数字必须能在某个 chart.series.value 中找到，且该 chart 的 source.quote 含该数字或其可直接换算的表述。
- 找不到来源的信息：不上图，写入 uncertainties 或 off_figure_notes。禁止编造。

## panels

```json
{"id": "p1", "role": "question", "title": "Research question", "grid": [0, 0]}
```
- role ∈ question | methods | results | conclusion。四要素各至少一个面板（conclusion 面板可与其他合并，但 conclusion.text 必须有落点）。
- grid=[row,col]，从 0 开始。阅读顺序 = 行优先。推荐 2×2：question[0,0] methods[0,1] results[1,0] conclusion[1,1]；
  或 1×4 横排（流程感强时）。渲染器按 grid 自动等分画布。

## entities

```json
{"id": "e1", "panel": "p2", "label": "Glycoprotein GPX4", "kind": "molecule", "slot": [0, 0], "group": "treated", "source": {...}}
```
- kind ∈ molecule | cell | material | device | sample | process | complex。形状由 kind 决定（见 drawing_rules.md）。
- slot=[row,col]：面板内逻辑格位，渲染器自动等分。同一面板内 slot 不得重复。
- group 可选，引用 groups 键，用分组色浅填充（表达实验条件归属）。
- label ≤40 字符；过长会自动换行，但建议精炼。层级关系（分子在细胞内）用 contains 关系表达，不靠嵌套坐标。

## relations

```json
{"id": "r1", "from": "e1", "to": "e2", "type": "activates", "label": "phosphorylation", "source": {...}}
```
- type ∈ activates | inhibits | converts | contains | measures | flow。
- 方向必须与材料因果一致：from=作用方，to=被作用方。inhibits 渲染为 T 形端，activates/converts 为实心箭头，
  contains 为虚线菱形端，measures 为虚线箭头，flow 为灰色箭头（流程/物料方向）。
- label 可选，≤24 字符，标在线中点。

## charts（数据编码）

```json
{"id": "c1", "panel": "p3", "kind": "bar", "title": "Cell viability",
 "unit": "%", "scale": {"min": 0, "max": 100},
 "series": [{"id": "s1", "label": "Control", "value": 92.1, "group": "control"},
            {"id": "s2", "label": "Treated", "value": 41.3, "group": "treated"}],
 "source": {...}}
```
- kind ∈ bar | line。**bar** 用柱长编码（默认，最稳健，须从 0 起）；**line** 用折线连接有序 x 类别的点（剂量响应/时间序列），同一 group 的 series 连成一条线，颜色取该 group，点为圆形标记，可带误差棒。value 必须是材料中的真实数值，禁止取整美化（渲染器按原值标注，`:g` 最短表示，长浮点原文只进溯源）。
- **有 CSV/XLSX 源数据文件时必须用 scripts/ingest_data.py 直读生成 chart**（单元格级溯源），禁止 LLM 手工转录数字；用 `--kind line` 直接生成折线片段。
- series 可选字段：`error`（±值，材料给了 SD/SEM 才画误差棒）、`category`（仅 bar：同一 category 的 series 并排成组，x 轴标 category，组色仍来自 groups）。
- scale 必须覆盖所有 value（含 value+error）；bar 的 min 固定为 0（避免夸大差异）；line 的 min 可按数据范围设定。
- 每个 series 必须有 group；颜色只来自 groups，渲染器自动生成图例，保证图例↔柱色一一对应。
- 同一面板可同时有 entities 和 chart：实体占上半区，图表占下半区。

## groups（色觉安全）

```json
{"control": {"label": "Control", "color": "#0072B2"},
 "treated": {"label": "Treated", "color": "#D55E00"}}
```
- 默认从 assets/palettes.json 的 Okabe-Ito 色盲安全色板取色；两两灰度亮度差应≥0.15（校验器会查）。
- 分组数 >4 时警告：建议合并或改用分面。

## uncertainties

```json
{"item": "IC50 数值", "reason": "材料仅给区间 10–20 µM，无点值", "handling": "图中不标数值，图注注明区间；已写入 result.json"}
```

## 渲染器自动嵌入的语义属性（勿手写）

渲染器在每个 SVG 元素上写入 `data-source`（溯源）、`data-kind/panel/slot/group/label`（实体）、
`data-from/to/type`（关系）、`data-value/error/category`（数据柱）、`data-role/grid`（面板）等，
并在 `<metadata id="provenance">` 内嵌完整溯源 JSON。这使 `svg_to_spec.py` 能从任何
（含手工编辑过的）SVG 精确重建 spec，实现保源编辑与最小变更 diff。跨面板关系自动走
顶部走廊的正交折线，避免穿过无关实体。