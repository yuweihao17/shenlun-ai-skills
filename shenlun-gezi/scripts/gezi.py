#!/usr/bin/env python3
"""Shenlun answer-sheet grid & character counter (Guokao 25-cell-per-row standard).

Models real Chinese civil service exam (Shenlun) 25-cell-per-row answer-sheet rules:
- 1 Chinese character / full-width punctuation = 1 cell
- Wide punctuation ('——', '……') = 2 cells, NEVER split across rows or compressed into 1 cell
  (if only 1 cell remains at row end, leave it blank and move the full 2-cell mark to next row)
- Line-start closing/pause punctuation squeeze: if '。！？，、；：”’）' falls on col 1 after a full row,
  squeeze it into the previous row's last cell
- Line-end opening punctuation avoidance (行末避头): if '“‘（《【' lands on the final cell (col 25),
  leave col 25 blank and move it to col 1 of the next row
- Paired half-width alphanumerics & numeric decimals/percentages (e.g. '2026' -> 2 cells,
  '0.28' -> 2 cells, '97.6%' -> 3 cells)
- Ordinal prefixes at line/sentence start ('1.', '1、', '一、', '(1)', '（一）') = 1 cell
- Compound punctuation ('：“', '。”', '”。', '”、', '”；', '？！', etc.) = 1 cell
- Mixed official-document / essay layouts (--doc-mode):
  * none: uniform --indent for every paragraph
  * essay / gongwen: line 1 centered title (indent=0), body paragraphs indent=2
  * gongwen-speech: line 1 title (indent=0), line 2 salutation (indent=0), body indent=2
  * gongwen-full: line 1 title (indent=0), line 2 salutation (indent=0), last 2 lines signoff (indent=0), middle body indent=2
- Actionable revision feedback:
  * Line-saving hints (省行提示) when a paragraph ends with a <=6-cell tail
  * Under-use warning (格数剩太多预警) when strict-mode usage is below 80% of limit
  * Approx mode with optional --hard-max ceiling
  * Exact coordinates ("第X行第Y格") and optional row-by-row grid preview (--preview)
"""

import argparse
import json
import re
import sys

OPENING_PUNCT = set("“‘（〔［【《〈(")
CLOSING_OR_PAUSE_PUNCT = set("。！？，、；：”’）〕］】》〉)")
SENTENCE_END_OR_COLON = set("。！？：；…")

COMPOUND_PUNCT = {
    "：“", "。”", "”。", "！”", "”！", "？”", "”？",
    "”，", "”、", "”；", "，\"", "；”", "：’", "。’", "’。", "’、", "’；",
    "？！", "！？", "？？", "！！",
    "》：", "》、", "》，", "》。", "《“", "《‘",
    "）：", "）、", "），", "）。",
    "，”", "》；",
}

OPENING_COMPOUND = {
    "\uff0c\u201c",  # ，“
    "\u3001\u201c",  # 、“
    "\uff1b\u201c",  # ；“
}

ORDINAL_RE = re.compile(
    r"^(?:"
    r"[（(](?:[一二三四五六七八九十百]+|\d{1,2})[）)]"
    r"|(?:\d{1,2}|[一二三四五六七八九十]+)[、.．)）]"
    r")"
)

NUMERIC_RUN_RE = re.compile(r"^\d+(?:\.\d+)?%?")


def normalize_punct(text: str) -> str:
    """把 ASCII 直引号转成中文左右引号。

    申论卷面必须用全角引号；而且只有中文引号才能与句号、冒号组成复合标点合占 1 格
    （。" / ，" / ：" 匹配不上复合标点表，会白白多占一格，卷面也不规范）。
    """
    out = []
    opening = True
    for ch in text:
        if ch == '"':
            out.append("\u201c" if opening else "\u201d")
            opening = not opening
        else:
            out.append(ch)
    # 冒号只在「汉字 + 引号」之间才当中文冒号处理，避免误伤 19:00、http: 这类写法
    chars = list(out)
    for i, ch in enumerate(chars):
        if ch == ":" and 0 < i < len(chars) - 1:
            prev, nxt = chars[i - 1], chars[i + 1]
            if "\u4e00" <= prev <= "\u9fff" and nxt in "\u201c\u201d":
                chars[i] = "\uff1a"
    return "".join(chars)


def tokenize(text: str):
    """Split text into grid tokens: (text, width, kind)."""
    tokens = []
    i = 0
    n = len(text)
    at_sentence_or_line_start = True

    while i < n:
        ch = text[i]

        if ch == "\r":
            i += 1
            continue
        if ch == "\n":
            tokens.append(("\n", 0, "newline"))
            at_sentence_or_line_start = True
            i += 1
            continue

        if ch in (" ", "\t", "\u3000"):
            i += 1
            continue

        # Ordinal prefix at line/sentence start
        if at_sentence_or_line_start:
            m = ORDINAL_RE.match(text[i:])
            # 「97.6%」这类小数不能被误判成序号「97.」
            if m and m.group(0)[-1] in ".．" and text[i + len(m.group(0)):i + len(m.group(0)) + 1].isdigit():
                m = None
            if m:
                ord_str = m.group(0)
                tokens.append((ord_str, 1, "ordinal"))
                i += len(ord_str)
                at_sentence_or_line_start = False
                continue

        # Wide punctuation: —— or …… (fixed 2 cells, never split)
        if text[i:i + 2] in ("——", "……"):
            tokens.append((text[i:i + 2], 2, "wide_punct"))
            at_sentence_or_line_start = text[i:i + 2] == "……"
            i += 2
            continue

        # 含前引号的复合标点（，/、/； + “）
        if i + 1 < n and text[i:i + 2] in OPENING_COMPOUND:
            tokens.append((text[i:i + 2], 1, "compound_open"))
            at_sentence_or_line_start = False
            i += 2
            continue

        # Compound 2-char punctuation
        if i + 1 < n and text[i:i + 2] in COMPOUND_PUNCT:
            pair = text[i:i + 2]
            tokens.append((pair, 1, "compound_punct"))
            at_sentence_or_line_start = pair[-1] in SENTENCE_END_OR_COLON
            i += 2
            continue

        # Numeric run including decimal point and trailing '%' -> 2 chars per cell
        if ch.isascii() and ch.isdigit():
            m_num = NUMERIC_RUN_RE.match(text[i:])
            num_str = m_num.group(0) if m_num else ch
            for k in range(0, len(num_str), 2):
                tokens.append((num_str[k:k + 2], 1, "digits"))
            at_sentence_or_line_start = False
            i += len(num_str)
            continue

        # Consecutive ASCII letters -> 2 per cell
        if ch.isascii() and ch.isalpha():
            j = i
            while j < n and text[j].isascii() and text[j].isalpha():
                j += 1
            alpha_str = text[i:j]
            for k in range(0, len(alpha_str), 2):
                tokens.append((alpha_str[k:k + 2], 1, "alpha"))
            at_sentence_or_line_start = False
            i = j
            continue

        # Single punctuation
        if ch in OPENING_PUNCT:
            tokens.append((ch, 1, "open_punct"))
            at_sentence_or_line_start = False
            i += 1
            continue

        if ch in CLOSING_OR_PAUSE_PUNCT:
            tokens.append((ch, 1, "close_punct"))
            at_sentence_or_line_start = ch in SENTENCE_END_OR_COLON
            i += 1
            continue

        # Regular character (Hanzi, etc.)
        tokens.append((ch, 1, "char"))
        at_sentence_or_line_start = False
        i += 1

    return tokens


def _paragraph_role_and_indent(p_idx: int, total_paras: int, default_indent: int, doc_mode: str):
    """Determine (role, indent, full_row_dedicated) for a paragraph under doc_mode."""
    if doc_mode == "none":
        return ("body", default_indent, False)
    if doc_mode in ("essay", "gongwen"):
        if p_idx == 0:
            return ("title", 0, True)
        return ("body", 2 if default_indent == 0 else default_indent, False)
    if doc_mode == "gongwen-speech":
        if p_idx == 0:
            return ("title", 0, True)
        if p_idx == 1:
            return ("salutation", 0, True)
        return ("body", 2 if default_indent == 0 else default_indent, False)
    if doc_mode == "gongwen-full":
        if p_idx == 0:
            return ("title", 0, True)
        if p_idx == 1 and total_paras > 3:
            return ("salutation", 0, True)
        if total_paras >= 4 and p_idx >= total_paras - 2:
            return ("signoff", 0, True)
        return ("body", 2 if default_indent == 0 else default_indent, False)
    return ("body", default_indent, False)


def layout_grid(
    text: str,
    cols: int = 25,
    indent: int = 0,
    doc_mode: str = "none",
    tail_threshold: int = 6,
    include_preview: bool = False,
    include_rows: bool = False,
):
    """Simulate row-by-row grid layout and compute exact cell consumption."""
    text = normalize_punct(text)
    paragraphs = [p for p in text.split("\n") if p.strip() != ""]
    total_paras = len(paragraphs)
    rows = []
    row_roles = []
    row_paras = []
    para_stats = []
    line_saving_hints = []
    total_token_cells = 0

    for p_idx, para in enumerate(paragraphs):
        role, p_indent, is_dedicated = _paragraph_role_and_indent(p_idx, total_paras, indent, doc_mode)
        tokens = tokenize(para)
        current_row = []
        col = 0
        p_rows = 1
        p_token_cells = 0

        if p_indent > 0:
            for _ in range(min(p_indent, cols)):
                current_row.append("□")
                col += 1

        for tok_text, width, kind in tokens:
            p_token_cells += width
            total_token_cells += width

            # 1. Line-start closing/pause punctuation squeeze into previous row's last cell
            if col == cols and kind in ("close_punct", "compound_punct"):
                if current_row:
                    current_row[-1] = current_row[-1] + tok_text
                continue

            # 2. Line-end opening punctuation avoidance (行末避头): never place opening punct in last cell
            if kind == "open_punct" and col == cols - 1:
                rows.append(current_row)
                row_roles.append(role)
                row_paras.append(p_idx + 1)
                current_row = [tok_text]
                col = 1
                p_rows += 1
                continue

            # 2b. 「，+前引号」落在行末最后一格：逗号留在本行，引号移到下一行行首
            if kind == "compound_open" and col == cols - 1:
                current_row.append(tok_text[0])
                col += 1
                rows.append(current_row)
                row_roles.append(role)
                row_paras.append(p_idx + 1)
                current_row = [tok_text[1]]
                col = 1
                p_rows += 1
                continue

            # 3. Normal wrap (including wide_punct '——'/'……' when col == cols - 1: leave last cell blank, move intact)
            if col + width > cols:
                rows.append(current_row)
                row_roles.append(role)
                row_paras.append(p_idx + 1)
                current_row = []
                col = 0
                p_rows += 1

            if width == 2:
                current_row.append(tok_text[0])
                current_row.append(tok_text[1])
                col += 2
            else:
                current_row.append(tok_text)
                col += 1

        trailing_empty = cols - col
        rows.append(current_row)
        row_roles.append(role)
        row_paras.append(p_idx + 1)
        para_stats.append({
            "paragraph": p_idx + 1,
            "role": role,
            "rows": p_rows,
            "last_row_filled": col,
            "trailing_empty_cells": trailing_empty,
            "token_cells": p_token_cells,
            "dedicated_row": is_dedicated,
        })

        # Line-saving hint for non-dedicated body paragraphs with a small tail on row 2+
        if not is_dedicated and p_rows >= 2 and 1 <= col <= tail_threshold:
            line_saving_hints.append(
                f"第{p_idx + 1}段末行仅占{col}格（空{trailing_empty}格），删减{col}格即可省出1整行（{cols}格）"
            )

    total_rows = len(rows)
    if total_rows == 0:
        consumed_cells = 0
        final_col = 0
    else:
        if para_stats and para_stats[-1]["role"] == "signoff":
            consumed_cells = total_rows * cols
            final_col = cols
        else:
            final_col = len(rows[-1])
            consumed_cells = (total_rows - 1) * cols + final_col

    wasted_cells = sum(p["trailing_empty_cells"] for p in para_stats[:-1]) if para_stats else 0
    raw_chars = len(re.sub(r"\s+", "", text))

    result = {
        "columns_per_row": cols,
        "indent_per_paragraph": indent,
        "doc_mode": doc_mode,
        "raw_non_whitespace_chars": raw_chars,
        "token_cells_without_newlines": total_token_cells,
        "total_rows": total_rows,
        "final_row": total_rows,
        "final_col": final_col,
        "total_grid_cells_consumed": consumed_cells,
        "wasted_cells_from_newlines": wasted_cells,
        "line_saving_hints": line_saving_hints,
        "paragraphs": para_stats,
    }

    # 格数与版式诊断：结构类（可省格）与观感类（孤字行）分开报
    advice = []
    total_waste = sum(p["trailing_empty_cells"] for p in para_stats[:-1]) if para_stats else 0
    layout_first = doc_mode != "none"   # 大作文/公文：美观优先，不建议合并段落
    ROLE_CN = {"title": "标题", "salutation": "称谓", "signoff": "落款"}
    for idx, p in enumerate(para_stats):
        role, no = p["role"], p["paragraph"]
        empty, used = p["trailing_empty_cells"], p["last_row_filled"]
        raw = paragraphs[idx].strip() if idx < len(paragraphs) else ""
        is_sentence = raw.endswith(("。", "！", "？", "；", "……", "”"))
        if role in ROLE_CN:
            advice.append({"paragraph": no, "save": 0, "kind": "format",
                           "tip": f"第{no}段（{ROLE_CN[role]}）独立成行，属格式必占，不要动"})
            continue
        if 1 <= used <= 5 and p["rows"] >= 1:
            advice.append({"paragraph": no, "save": 0, "kind": "aesthetic",
                           "tip": f"第{no}段末行只剩{used}格（孤字行），补到8格以上或删到整行满格更齐整"})
            continue
        if layout_first:
            continue
        if p["rows"] == 1 and used <= 14 and not is_sentence:
            advice.append({"paragraph": no, "save": empty, "kind": "structure",
                           "tip": f"第{no}段只写了{used}格却独占一行，疑似小标题；并进下一段可回收{empty}格"})
        elif empty >= 8:
            advice.append({"paragraph": no, "save": empty, "kind": "structure",
                           "tip": f"第{no}段末行只占{used}格，空{empty}格；删{used}格或与下段合并可省一整行"})
    advice.sort(key=lambda x: (-x["save"], x["kind"] != "aesthetic"))
    result["waste_summary"] = {
        "paragraphs": len(para_stats),
        "wasted_cells": total_waste,
        "wasted_rows": round(total_waste / cols, 1),
        "recoverable": sum(a["save"] for a in advice),
    }
    result["advice"] = advice[:6]

    if include_rows:
        result["rows"] = rows
        result["row_roles"] = row_roles
        result["row_paragraphs"] = row_paras

    if include_preview:
        preview_lines = []
        for idx, r in enumerate(rows, 1):
            padded = r + ["·"] * (cols - len(r))
            preview_lines.append(f"行{idx:02d} | {' '.join(padded)} | ({len(r):02d}/{cols})")
        result["grid_preview"] = preview_lines

    return result


def _apply_limit(result: dict, limit: int, mode: str, hard_max: int = 0):
    consumed = result["total_grid_cells_consumed"]
    cols = result["columns_per_row"]
    f_row = result["final_row"]
    f_col = result["final_col"]

    if limit <= 0:
        result["summary"] = f"按{cols}格答题卡排版：写到第{f_row}行第{f_col}格，共占{consumed}格"
        return result

    pct = round(consumed / limit * 100, 1)
    warnings = []

    if mode == "strict":
        if consumed > limit:
            status = f"OVERFLOW (+{consumed - limit} cells)"
        elif consumed < int(limit * 0.85):
            status = f"PASS (UNDERUSED: {pct}% < 85%)"
            warnings.append(
                f"格数偏少（仅用{consumed}/{limit}格，占{pct}%，低于85%），可能漏了材料采分点，建议核对材料补全要点"
            )
        else:
            status = "PASS"
    else:
        low = int(limit * 0.9)
        high = int(limit * 1.1)
        if hard_max > 0 and consumed > hard_max:
            status = f"OVER_HARD_MAX (+{consumed - hard_max} cells above {hard_max})"
        elif low <= consumed <= high:
            status = "PASS (within +/-10%)"
        elif consumed < low:
            status = f"UNDER (-{low - consumed} cells below 90%)"
        else:
            status = f"OVER (+{consumed - high} cells above 110%)"

    result["limit"] = limit
    result["mode"] = mode
    if hard_max > 0:
        result["hard_max"] = hard_max
    result["usage_percent"] = pct
    result["status"] = status
    if warnings:
        result["warnings"] = warnings
    if "advice" in result:
        if consumed > limit:
            result["advice_notes"] = "已超格：按 advice 顺序删减，先动结构再动措辞"
        elif pct < 85:
            result["advice_notes"] = "字数偏少：先回材料补要点，版式建议仅供参考"
        else:
            result["advice_notes"] = "已达标：下列为可选优化，不改也不扣分，美感优先时不建议动"
    result["summary"] = (
        f"按{cols}格答题卡排版：写到第{f_row}行第{f_col}格，共占{consumed}/{limit}格（{pct}%），状态：{status}"
    )
    return result


def _selftest():
    """自检：文档里承诺的每一条规则，都必须真的成立。"""
    pairs = ["。”", "，”", "：“", "，“", "、“", "；“", "”。", "？！", "》；", "）。", "》，", "”，"]
    fails = []
    for pr in pairs:
        t = tokenize("甲" + pr + "乙")
        if not (len(t) == 3 and t[1][1] == 1):
            fails.append("复合标点未合并：" + pr)
    # 行末避头：逗号留本行，前引号移到下一行行首
    r = layout_grid("甲" * 24 + "，“乙", cols=25, include_rows=True)
    rows = r["rows"]
    if not (rows[0][-1] == "，" and rows[1][0] == "“"):
        fails.append("行末避头失效：前引号被留在了行末")
    # 两个半角字符挤一格
    if layout_grid("2026", cols=25)["total_grid_cells_consumed"] != 2:
        fails.append("半角数字未两两挤格")
    # 阿伯数字与汉字对照
    if not layout_grid("97.6%", cols=25)["total_grid_cells_consumed"] == 3:
        fails.append("百分数未挤格")
    if fails:
        print("自检未通过：")
        for f in fails:
            print("  ✘", f)
        return 1
    print("自检通过：复合标点 12 对全部合 1 格，行末避头生效，半角挤压正常。")
    return 0


def main():
    import argparse
    NL = chr(10)
    parser = argparse.ArgumentParser(description="申论答题卡格数核算（25格/行标准版）")
    parser.add_argument("--text", type=str, help="直接传入文本")
    parser.add_argument("-f", "--file", type=str, help="UTF-8 文本文件路径")
    parser.add_argument("-w", "--width", "--cols", dest="cols", type=int, default=25, help="每行格数，默认 25")
    parser.add_argument("-i", "--indent", type=int, default=0, help="段首缩进格数，默认 0")
    parser.add_argument("--doc-mode", choices=["none","essay","gongwen","gongwen-speech","gongwen-full"], default="none", help="混排模式")
    parser.add_argument("-l", "--limit", type=int, default=0, help="字数上限（0 = 不做上限检查）")
    parser.add_argument("--mode", choices=["strict","approx"], default="strict", help="strict=硬上限；approx=左右（正负10%%）")
    parser.add_argument("--about", action="store_true", help="等价于 --mode approx（题干写“XX字左右”）")
    parser.add_argument("--cells", type=int, default=0, help="答题卡实际格子数，等价于 --hard-max")
    parser.add_argument("--hard-max", type=int, default=0, help="approx 模式下的物理硬上限")
    parser.add_argument("--tail-threshold", type=int, default=6, help="省行提示阈值，默认 6")
    parser.add_argument("--preview", action="store_true", help="输出逐行格子预览")
    parser.add_argument("--no-grid", action="store_true", help="不输出格子预览")
    parser.add_argument("--selftest", action="store_true", help="运行内置规则自检")
    args = parser.parse_args()

    if args.selftest:
        raise SystemExit(_selftest())

    if args.about:
        args.mode = "approx"
    if args.cells and not args.hard_max:
        args.hard_max = args.cells
    if args.no_grid:
        args.preview = False

    if args.text is not None:
        text = args.text
    elif args.file:
        with open(args.file, "r", encoding="utf-8") as f:
            text = f.read()
    else:
        text = sys.stdin.read()

    result = layout_grid(text, cols=args.cols, indent=args.indent, doc_mode=args.doc_mode,
                         tail_threshold=args.tail_threshold, include_preview=args.preview)
    result = _apply_limit(result, args.limit, args.mode, args.hard_max)

    if args.preview and "grid_preview" in result:
        preview = result.pop("grid_preview")
        print(json.dumps(result, ensure_ascii=False, indent=2))
        print()
        print("=== 逐行格子预览 ===")
        print(NL.join(preview))
    else:
        result.pop("grid_preview", None)
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
