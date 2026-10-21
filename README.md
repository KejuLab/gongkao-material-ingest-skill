# gongkao-material-ingest

![status: experimental](https://img.shields.io/badge/status-experimental-orange)
![license: MIT](https://img.shields.io/badge/license-MIT-blue)

> ⚠️ **实验性项目（EXPERIMENTAL）**
> 这个 skill 仍在作者自用测试阶段，接口、输出格式和判定逻辑都可能随时改变。
> 目前只在一类材料上验证过：中文单栏讲义（有文本层）+ 一种平板笔记应用的导出 PDF。
> **扫描件、复杂版面、表格公式、其他笔记软件的导出格式均未验证**；手写识别是有意保留的人工环节，准确率取决于使用者。请勿直接用于正式生产流程。

把一次课程的三类材料——**讲义 PDF**、**AI 总结 docx**、**写有手写作答的 PDF**——整理成可检索的 Markdown 和可核对的作答台账，再拿答案册比对出错题。

面向公考备考，但方法对任何"讲义 + 手写作答"的场景都通用：文字走文本层（逐字精确），只有手写才作为图像处理。

## 三个脚本

| 脚本 | 输入 | 输出 |
| --- | --- | --- |
| `pdf_structure.py` | 讲义或答案册 PDF | 结构化 Markdown：按字号与标题模式重建层级、剔除页眉页脚与目录点线、合并断行、把挤在一行的选项拆开 |
| `docx_to_md.py` | 带图片的 docx（如 AI 课程总结） | Markdown + 就地抽出的内嵌图片（课件截图），插在对应段落之后 |
| `ink_ledger.py` | 写有手写的 PDF | 作答台账（Markdown + JSON）+ 手写字母小图 + 拼版图 |

## 安装

一个技能就是一个文件夹 + 一个 `SKILL.md`。把本仓库的 `SKILL.md` 和 `scripts/` 放进技能目录即可，注意两点：

- **目标文件夹必须叫 `gongkao-material-ingest`**。工具用文件夹名当技能名，且要和 `SKILL.md` 里 frontmatter 的 `name` 一致；直接 clone 会得到 `gongkao-material-ingest-skill`，装上去可能认不到。
- 装完重开窗口（Cursor 里也可以 `Developer: Reload Window`），让它重新发现技能。

### 方式一：让 Agent 帮你装（把这段话复制给它）

**装到项目级**（只对当前项目生效，适合固定工作区）：

```
把 https://github.com/KejuLab/gongkao-material-ingest-skill 装成本项目的技能：
clone 后把 SKILL.md 和 scripts/ 复制到 .agents/skills/gongkao-material-ingest/，
目标文件夹名必须是 gongkao-material-ingest；再按 requirements.txt 装依赖，装完告诉我路径。
```

**装到用户级**（对本机所有项目生效，不想每个项目都装一遍就用这个）：

```
把 https://github.com/KejuLab/gongkao-material-ingest-skill 装成用户级技能：
clone 后把 SKILL.md 和 scripts/ 复制到 ~/.cursor/skills/gongkao-material-ingest/
（Windows 为 %USERPROFILE%\.cursor\skills\gongkao-material-ingest\），
目标文件夹名必须是 gongkao-material-ingest；再装依赖，装完告诉我路径。
```

用 Claude Code 或 Codex 的，把上面路径换成下表对应的一行即可。

### 方式二：一条命令（Windows / macOS / Linux 都能跑）

```bash
python install.py                                  # 交互式选择装到哪
python install.py --tool cursor --scope project    # 当前项目的 .agents/skills/
python install.py --tool cursor --scope user       # 用户级 ~/.cursor/skills/
python install.py --tool claude --scope user       # ~/.claude/skills/
python install.py --target ~/skills/gongkao-material-ingest
python install.py --dry-run ...                    # 只看计划，不写文件
python install.py ... --with-deps                  # 顺带 pip install -r requirements.txt
```

`install.py` 只用标准库（装依赖之前就能跑），会自动把目标目录名对齐成 `gongkao-material-ingest`，目标目录里有无关文件时会拒绝覆盖，除非加 `--force`。

### 方式三：手动复制

把本仓库的 `SKILL.md` 与 `scripts/` 放进下表中的 `gongkao-material-ingest/` 子目录：

| 工具 | 项目级 | 用户级 |
| --- | --- | --- |
| Cursor | `<项目>/.agents/skills/` 或 `<项目>/.cursor/skills/` | `~/.cursor/skills/` |
| Claude Code | `<项目>/.claude/skills/` | `~/.claude/skills/` |
| Codex | `<项目>/.codex/skills/` | `~/.codex/skills/` |
| 通用 | `<项目>/.agents/skills/` | `~/.agents/skills/` |

> 仓库里的 `install.ps1` 只是作者本机把仓库同步到自己的技能目录用的，不是给使用者的安装方式。
> 另外不建议用符号链接：官方文档没有承诺技能目录支持 symlink，社区反馈也不一致，复制最稳。

## 依赖

```bash
pip install -r requirements.txt
```

- Python 3.9+，四个包：`pymupdf`、`pillow`、`numpy`、`scipy`。
- **不需要** pandoc、LibreOffice、Node、.NET，也没有任何系统级命令行依赖。
- 装完约占 180 MB（scipy 约 90 MB、pymupdf 约 53 MB、numpy 约 31 MB、pillow 约 3 MB）。

## 快速开始

```bash
# 1. 讲义 -> Markdown
python scripts/pdf_structure.py "讲义.pdf" -o out/jiangyi.md

# 2. 课程总结 docx -> Markdown（图片抽到 out/docx-images）
python scripts/docx_to_md.py "总结.docx" -o out/wangke.md --imgdir out/docx-images

# 3. 手写 PDF -> 作答台账（含字母小图与拼版图）
python scripts/ink_ledger.py "作答.pdf" -o out/ink

# 4. 人工/模型识别字母后回填，再并进台账
python scripts/ink_ledger.py "作答.pdf" -o out/ink --answers out/ink/answers.csv
```

产物路径完全由调用方指定，脚本内部**不含任何固定路径**。

## 输入要求

### 讲义 PDF

- 需要有可提取的**文本层**。纯扫描件目前不支持（见 Roadmap）。
- 标题层级靠"字号 + 中文常见标题写法"（`第X章`、`1.1`、`一、`、`（一）`、`例题 N`）。写法差异大的文档会退化为只按字号分级，正文仍然完整。

### 带手写的 PDF

- 需要手写是**独立图层**：一张覆盖整页的图，用 alpha 通道存笔画、RGB 通道存笔色。
- **已验证范围**：作者只在一种导出形态上验证过——平板笔记软件导出 PDF 时，同时保留「页面图像 + 正文文本层 + 整页笔迹层」这三层。**其他笔记软件是否这样导出未知**，使用前请先自查。
- 自查方法：

  ```python
  import pymupdf, re
  doc = pymupdf.open("你的.pdf")
  page = doc[0]
  for info in page.get_image_info(xrefs=True):
      full = info["bbox"][0] <= 1 and info["bbox"][1] <= 1
      smask = "SMask" in doc.xref_object(info["xref"])
      print("整页图:", full, "| 带 alpha:", smask)
  ```

  如果出现「整页图 + 带 alpha」，则可以提取笔迹；若 PDF 已被扁平化（手写烘焙进页面图像），当前版本无法分离，只能退回像素差分（未实现）。

### 手写字母识别

脚本只负责把笔迹切成小图并排成拼版图；字母本身需要人或模型识别后回填 `answers.csv`（两列：`id,letter`，非字母项记 `-`）。这是有意的 human-in-the-loop 设计，而不是缺陷。

## 产物

```
out/
├── jiangyi.md            讲义，带层级
├── wangke.md             课程总结
├── docx-images/          课件截图
└── ink/
    ├── ink-ledger.md     台账：一题一行（划掉的选项 / 手写字母 / 判定）
    ├── ink-ledger.json   同数据的结构化版本
    ├── crops/            手写字母小图
    └── montage/          拼版图，每格标 id 与页码
```

体积参考：一门课约 10–15 MB。

## 已知限制

- 圈注、手写汉字会被当成字母候选，需要在拼版图里人工排除。
- 同一页有多道题时，字母与题目的归属靠纵坐标就近匹配，跨页题目偶尔会错位。
- 台账只能记录"选了什么、划了什么"；判定对错必须另有答案来源（答案册或带选项分析的讲解文档）。

## Roadmap

- **扫描件 OCR 兜底**：无文本层的讲义接入 OCR。
- **自动字母识别**：接 OCR 或多模态模型，免去人工回填。
- **表格抽取**：面向资料分析类讲义中的统计表。
- **扁平化 PDF 适配**：与干净原版做像素差分，恢复笔迹。
- **答案册自动比对**：`--key` 参数直接输出「我的答案 / 正确答案 / 对错」。
- **去掉 scipy 依赖**：自实现连通域标记，可省约 90 MB。

## 与通用 PDF 解析工具（如 MinerU）的关系

**不是替代关系，而是分工不同。** 通用解析器（MinerU、docling、marker 等）用版面模型做阅读顺序、表格、公式与扫描件 OCR；本工具不做这些，它假设你要处理的是一份**有文本层的中文讲义**，并把力气花在两件通用工具不做的事上：按字号与中文标题写法还原层级、把平板笔迹变成作答台账。

| 能力 | 通用解析器（MinerU 等） | 本工具 |
| --- | --- | --- |
| 多栏 / 表格 / 公式 / 阅读顺序 | 有 | 无（单栏假设） |
| 扫描件 OCR | 有 | 无（未实现） |
| 标题层级 | 由模型判断，常被压成同级 | 按字号 + 中文标题写法重建 |
| 依赖与速度 | 重（模型，输出大量坐标 json） | 轻（4 个 Python 包，秒级） |
| 手写笔迹 → 作答记录 | 无 | **有，这是本工具存在的理由** |
| docx 读取 | 非主打 | 直接读 OOXML，保留样式层级与图片位置 |

结论：同一份讲义两者都能出 Markdown，本工具在这类材料上更准也更轻；遇到复杂版面或扫描件，仍应交给通用解析器。真正无法被替代的是笔迹那一层。

## 仓库说明

- 本仓库**不包含**任何教材、讲义或课程内容，只放脚本与文档。
- 目录约定（素材放哪、产物放哪）属于使用者自己的项目规范，不在本仓库内定义。

## License

MIT，见 [LICENSE](LICENSE)。

本项目按"实验性软件"提供，不附带任何担保。使用前请自行确认：材料来源是否允许处理、输出结果是否需要人工复核。
