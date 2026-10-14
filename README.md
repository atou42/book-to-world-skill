# Book to World · 通用拆书 Skill

给通用 agent 使用的拆书技能，把书籍、故事或同一世界的设定资料整理为 **Neta 兼容的 `world.json`**。不需要 Neta 浏览器扩展、登录态或 Cohub。

## 四档

| 模式 | 用途 |
| --- | --- |
| Quick | 阅读全部指定材料，提取可用的核心人物、地点、事件和规则 |
| Full（默认） | 完整覆盖重要及次要内容，合并别名、核对前后变化 |
| Turbo | 使用所在 agent 的并行能力，达到 Full 的覆盖范围 |
| Turbo Append | 并行阅读中持续补充已有条目，最终逐一检查所有人物的细节 |

Turbo Append 不表示向已有线上世界追加数据。四档默认都生成本地文件；并行模式的中间结果各自保存，最后由一个协调者合并。没有并行能力时会明确说明，由用户选择是否改用 Full。

## 输入与输出

内置读取 TXT、Markdown、HTML、DOCX、EPUB；文本 PDF 需另外安装 `pdftotext`，内置 PDF 调用支持 macOS/Linux。粘贴文本、链接和其他格式通过所在 agent 的读取工具接入。扫描件需要 OCR，无法读取的内容不会被当作已经读完。

单个文件上限 64 MiB，合并后的文字上限 32 MiB，文档压缩包展开上限 128 MiB。超过时明确报错，需要分批整理并保留全量范围记录。

交付包括：

- `world.json`：只有 `worldConfig` 和 `atoms`，符合仓库附带的 Neta Import V1 格式。
- `report.md`：档位、来源范围、数量、遗漏和检查结果。
- 来源记录与独立工作文件：保留原文位置、别名和事实依据，不混入用户可见的卡片。

当前输出格式接受中文或英文。其他语言原文需要选择翻译为其中一种；不会伪装语言标记。兼容性以仓库里的固定格式为准，本次未验证真实 Neta 导入。

## 使用

把本仓库作为一个技能目录交给支持 `SKILL.md` 的 agent。入口是 [SKILL.md](SKILL.md)，参考文件和脚本需随同保留。

例如在 Codex 中，克隆到自己的工作目录后，为它建立一个独立技能链接：

```bash
git clone git@github.com:atou42/book-to-world-skill.git
mkdir -p ~/.codex/skills
ln -s "$PWD/book-to-world-skill" ~/.codex/skills/book-to-world
```

如果同名技能已经存在，先确认其来源，不要覆盖。此私有仓库需要相应的 GitHub 访问权限。

运行脚本需要 Python 3.10+。输入整理使用标准库，输出检查需要 `jsonschema`：

```bash
python3 -m venv /tmp/book-to-world-venv
/tmp/book-to-world-venv/bin/python -m pip install -r requirements.txt
```

向 agent 提出请求：

> 用 $book-to-world 的 Full 档读取这本 EPUB，输出 Neta 兼容的世界文件。

> 用 Turbo Append 处理这些按顺序排列的章节，保留人物的动机、关系和变化。

也可以单独运行准备和检查工具；它们本身不调用模型、不执行拆书：

```bash
python3 scripts/prepare_source.py book.epub --output-dir ./book-source
/tmp/book-to-world-venv/bin/python scripts/validate_world.py ./world.json
```

`--output-dir` 必须是尚不存在的目录。多个输入按命令参数顺序处理。详细边界见 [输入说明](references/input.md) 和 [输出说明](references/output.md)。

## 检查

```bash
PYTHONDONTWRITEBYTECODE=1 /tmp/book-to-world-venv/bin/python -m unittest discover -s tests -v
```

打包时 47 项检查中 46 项通过；真实 PDF 转换检查因本机未安装 `pdftotext` 而跳过，PDF 缺依赖和损坏输入的失败处理已经覆盖。另做了独立 agent 的 Full 档故事试跑；这不代表大部头、多语言和并行两档都已完成实战验收。

来源与兼容范围见 [provenance.md](references/provenance.md)。示例故事为本包创作，示例 JSON 只演示字段，不代表完整拆书结果。
