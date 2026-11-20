# 申论 AI 技能包

一套给 AI 助手用的申论训练技能，覆盖**小题批改**、**大作文批改**、**答题卡格数核算**与**命题预判**。
按 Agent Skills 规范组织（每个技能一个 `SKILL.md` + `references/` 资料库），可直接放进支持 Skill 机制的 AI 客户端。

## 这套技能能做什么

| 技能 | 职责 |
|---|---|
| `shenlun-router` | 总调度：图片/文字输入处理、真题识别、命题预判、错题库、把批改分派给下面两个模块 |
| `shenlun-xiaoti` | 小题（归纳概括／综合分析／对策／公文）：读名师库，出**两版参考作答**（小马哥版 + 白鹭版）＋差异对照＋落点建议 |
| `shenlun-dawenti` | 大作文：袁东体系（累进四类文评分、AB/ABC 型模板、标题等式、开头六写法、分论点五步走、结尾三步走） |
| `shenlun-gezi` | 答题卡格数核算：按每行 25 格模拟排版，算真实占用格数；另附 PDF 答题纸生成器 |
| `shared` | 跨题型共享：错题库规则、表述升级词库、口语→规范词映射表、图片识读规范、Word 导出脚本 |

## 目录结构

```
shared/                    公共库
  SKILL.md
  references/error-bank-rules.md          错题库：8 维度分类、复发提醒
  references/expression-upgrade-rules.md  表述升级：口语转规范、金句库
  references/oral-to-formal-map.md        口语→规范词映射（约 200 条）
  references/image-reading-rules.md       试卷/手写图片识读
  scripts/export_docx.py                  Markdown 批改报告导出 Word

shenlun-router/            总调度
  SKILL.md
  references/prediction-methodology.md    命题预判方法

shenlun-xiaoti/            小题
  SKILL.md
  references/xiaoma-methodology.md        小马哥方法论（353 行）
  references/bai-lu-methodology.md        白鹭方法论（367 行）
  references/gongwen-format-rules.md      公文四类格式与占格预留
  references/scoring-rules.md             采分点覆盖法与评分输出模板
  references/writing-rules.md             作答铁律
  references/real-exams/                  真题库（5 套 + 模板 + 索引）

shenlun-dawenti/           大作文
  SKILL.md
  references/yuan-dong-methodology.md     袁东体系（498 行）
  references/fallback-eval-rules.md       无题干兜底评改

shenlun-gezi/              格数
  SKILL.md
  scripts/gezi.py                         格数核算（含 --selftest 自检）
  scripts/answer_sheet.py                 答题纸 PDF 生成（需 reportlab + 楷体字体）
```

## 怎么用

把整个目录放进客户端的 skills 目录即可。每个 `SKILL.md` 头部有 `name` 与 `description`，客户端据此决定何时调用。

格数核算：

```bash
python3 shenlun-gezi/scripts/gezi.py -f 答案.txt -l 250            # 硬上限 250
python3 shenlun-gezi/scripts/gezi.py -f 答案.txt -l 1100 --about   # “1000-1200字”
python3 shenlun-gezi/scripts/gezi.py -f 公文.txt -l 500 --doc-mode gongwen
python3 shenlun-gezi/scripts/gezi.py --selftest                    # 规则自检
```

答题纸 PDF：

```bash
python3 shenlun-gezi/scripts/answer_sheet.py -f 答案.txt -l 250 \
  -t "第一题 · 归纳概括" -m "10 分 ｜ 不超过 250 字" -o 答题纸.pdf
```

多题合订用 `--manifest 清单.json`。PDF 需要 `pip install reportlab`，并准备一个楷体 TTF（默认读 `/root/fonts/LXGWWenKai-Regular.ttf`，可用 `--font` 指定）。

## 两条设计原则

**格数优先固定每行 25 格。** 真实国考卷有 20 格/行的版本，但练习统一按 25 格，保证每次字数感一致。

**规则必须可自检。** `gezi.py --selftest` 会逐条验证复合标点是否合 1 格、行末避头是否生效、半角是否两两挤格。写在文档里的规则，只有自检通过才算数。

## 关于内容来源

`xiaoma-methodology.md`、`bai-lu-methodology.md`、`yuan-dong-methodology.md` 三份文件，是对公开课与讲义的**学习笔记式整理**，用于个人备考参考，并非官方教材。其中带有「已证实／已证伪／待验证」的证据标注，未经验证的说法不会被当作评分依据。

请勿用于商业分发。如原作者有异议，删除对应文件即可，其余模块可独立运行。

## 已知限制

- 名师库中的方法论各有适用范围，技能里用「验证状态矩阵」标注了哪些结论有真题答案支撑、哪些没有，批改时以标注为准。
- 图片识读依赖客户端本身的多模态能力，本技能只提供识读流程与校验规则。
- 真题库目前收录 5 套，匹配不到时会提示用户补充题干，不会硬套。
