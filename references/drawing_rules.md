# 抽取与绘图规则（科学正确性核心）

## 目录
1. 材料读取
2. 四要素→面板映射
3. 实体识别与层级
4. 关系方向判定
5. 数据编码规则
6. 版式与阅读顺序
7. 失败与歧义处置

## 1. 材料读取
- 逐个真实读取 /input 下的材料文件。PDF 用 `pdftotext -layout` 或 pypdf 逐页提取；
  含关键图的 PDF 页要转图查看（pdftoppm）。禁止凭文件名/标签推断内容。
- 建立来源清单：每个文件记录 路径、类型、页/段定位方式。后续所有 source 引用它。
- 材料互相矛盾时：以任务说明指定的主来源为准（如 figure03 以指定生物学来源为准），
  矛盾写入 uncertainties，不悄悄取舍。

## 2. 四要素→面板映射
先写一张"面板—要点"清单再动手：
- question：研究对象 + 待解决问题（1–2 个实体 + 1 句问题）。
- methods：技术路线（process 实体链 + flow/measures 关系），只画主干，细节进图注。
- results：核心定量结果（charts）+ 关键机制发现（entities+relations）。
- conclusion：一句话结论（conclusion.text），可含 1 个推论箭头。
必须上图：研究对象、主线方法、核心数值、因果方向、分组条件、单位。
只能进图注（off_figure_notes）：样本量、统计检验细节、仪器型号、次要对照、实验批次。

## 3. 实体识别与层级
- 同一分子/蛋白/材料在全文可能多种写法（缩写、全称、别名）→ 归并为一个实体 id，
  label 用材料中最常见的规范名；别名记入 uncertainties 或 off_figure_notes。
- kind 判定：蛋白/小分子/基因=molecule；细胞系/细胞类型=cell；聚合物/合金/薄膜=material；
  芯片/传感器/器件=device；血清/组织样本=sample；实验步骤/处理=process；复合物=complex。
- 空间层级用 contains 关系（cell contains molecule），不要试图用坐标嵌套表达。
- 尺度：图形摘要不要求真实比例尺；若材料给了明确尺度且任务要求，写进 off_figure_notes 并在图注说明。

## 4. 关系方向判定（最易错，逐条核对）
- "A activates/upregulates/promotes B" → activates, from=A, to=B。
- "A inhibits/suppresses/blocks B"、"B is inhibited by A" → inhibits, from=A, to=B（注意被动语态反转）。
- "A is converted to B"、"A→B 代谢" → converts, from=A, to=B。
- "we measured B in A" → measures, from=A(方法/样本), to=B(读出)。
- 流程步骤先后 → flow。
- 每条关系写完立即回读 source.quote，确认方向与原文一致；双向/反馈关系拆成两条。

## 5. 数据编码规则
- 数值编码：离散类别→柱长（bar，分组→颜色）；有序浓度/时间→折线（line，点+连线）。禁止用面积/亮度编码精确数值。
- bar 的 y 轴从 0 起（scale.min=0），除非材料是对数尺度且任务明确要求；line 按数据范围设定尺度，点按 x 类别等距排列。
- 单位必须来自材料（%、µM、fold change…），写在轴上；无单位量纲写 "a.u." 并在 uncertainties 说明。
- 数值原样上图，不四舍五入到"好看"的数；误差棒材料未给就不画，写入 uncertainties。
- 颜色只用 Okabe-Ito 色板（assets/palettes.json）；灰度打印下两组亮度差≥0.15。
- 图例由渲染器自动生成，禁止手写图例文字与色块（防止图例↔数据错位）。

## 6. 版式与阅读顺序
- 默认 180×120 mm 横版，2×2 面板，行优先阅读：question→methods→results→conclusion。
- 面板编号徽章由渲染器按阅读顺序自动标注（①②③④），读者不迷路。
- 字号层级（mm）：图题 4.5 > 面板题 3.4 > 结论 3.2 > 实体标签 2.8 > 图例 2.6 > 刻度 2.2。
  校验器强制最小 2.2mm（≈6.2pt，300dpi 下清晰）。
- 每面板实体 ≤6 个、关系标签 ≤24 字符；超了就精炼语言，不是缩小字号。

## 7. 失败与歧义处置
| 情况 | 处置 |
|---|---|
| 关键数值缺失 | 不编造；该图表降级为定性关系图，uncertainties 记录，result.json status=partial |
| 实体歧义（同名不同物） | 用上下文（物种/细胞系/章节）消歧；无法消歧则两个候选都列出并写 uncertainties，图上取证据更强的一个并标注 |
| 文字溢出 | 渲染器自动换行；校验器报 overflow 警告时精炼 label，禁止缩字号 |
| 画布超限 | 校验器报错；减少面板内元素或改 1×4 布局，禁止超画布绘制 |
| 字体缺失 | 导出脚本检测并记录；CJK 材料优先用英文 label（学术惯例），保留中文原文在 source.quote |
| 导出失败 | 依次降级 cairosvg→pymupdf→rsvg-convert→inkscape（pymupdf 可纯 pip 安装）；全失败则保留 SVG，result.json 如实记录 export_checks.failed |
| 材料无法读取 | status=failed，写明哪个文件、什么原因；已能画的部分照常交付并标 partial |