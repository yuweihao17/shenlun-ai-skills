#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""申论答题纸 PDF 生成器。

把一段申论答案按答题卡格数规则排版后，用正楷字体逐字写进格子，
输出可直接打印的 A4 答题纸 PDF。

用法一（单题）：
  python3 answer_sheet.py -f ans.txt -l 250 -t "第一题 归纳概括" -m "10分｜不超过250字" -o q1.pdf

用法二（多题合订，一个 PDF）：
  python3 answer_sheet.py --manifest exam.json -o 全卷.pdf
  exam.json 形如：
  [{"title":"第一题 归纳概括","meta":"10分｜不超过250字","file":"q1.txt","limit":250,"doc_mode":"none"},
   {"title":"第五题 大作文","meta":"35分｜1000-1200字","file":"q5.txt","limit":1100,"doc_mode":"essay","approx":true}]
"""

import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from gezi import layout_grid, _apply_limit

from reportlab.pdfgen import canvas as rl_canvas
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

PW, PH = A4
HEADER_H = 80        # 页眉总高（标题＋副标题＋分隔线）
BOTTOM_RESERVED = 64 # 页脚预留高度，避免末行与页脚相撞
FONT_CANDIDATES = [
    "/root/fonts/LXGWWenKai-Regular.ttf",
    "/root/fonts/LXGWWenKai-Medium.ttf",
    os.path.join(HERE, "..", "fonts", "LXGWWenKai-Regular.ttf"),
]

GRID_GRAY = (0.72, 0.72, 0.72)
TEXT_BLACK = (0.07, 0.07, 0.07)
HEAD_GRAY = (0.35, 0.35, 0.35)
LIGHT_GRAY = (0.55, 0.55, 0.55)


def pick_font(explicit=None):
    if explicit:
        if not os.path.exists(explicit):
            raise SystemExit("字体文件不存在：" + explicit)
        return explicit
    for p in FONT_CANDIDATES:
        if os.path.exists(p):
            return os.path.abspath(p)
    import glob
    hits = glob.glob("/root/fonts/*.ttf") + glob.glob(os.path.join(HERE, "..", "fonts", "*.ttf"))
    if hits:
        return os.path.abspath(hits[0])
    raise SystemExit("未找到楷体字体文件，请用 --font 指定")


def register(font_path):
    pdfmetrics.registerFont(TTFont("Kai", font_path))
    return "Kai"


def measure(text, size):
    return pdfmetrics.stringWidth(text, "Kai", size)


def draw_grid(c, x0, y_top, cols, rows, cell):
    c.setStrokeColorRGB(*GRID_GRAY)
    c.setLineWidth(0.45)
    w = cols * cell
    h = rows * cell
    for i in range(cols + 1):
        x = x0 + i * cell
        c.line(x, y_top, x, y_top - h)
    for j in range(rows + 1):
        y = y_top - j * cell
        c.line(x0, y, x0 + w, y)


def draw_cells(c, x0, y_top, row_items, roles, cols, cell, size, start_index):
    for r, cells in enumerate(row_items):
        role = roles[r] if r < len(roles) else "body"
        n = len(cells)
        if n == 0:
            continue
        offset = 0
        if role == "title":
            offset = max(0, (cols - n) // 2)
        elif role == "signoff":
            offset = max(0, cols - n - 2)
        usable = min(n, cols - offset)
        for k in range(usable):
            tok = cells[k]
            if tok == "□":
                continue
            col_idx = offset + k
            cx = x0 + col_idx * cell + cell / 2.0
            cy = y_top - r * cell - cell / 2.0 - size * 0.34
            c.setFont("Kai", size)
            if len(tok) > 1:
                tw = pdfmetrics.stringWidth(tok, "Kai", size)
                squeeze = 1.0
                if tw > cell * 0.96:
                    squeeze = cell * 0.96 / tw
                c.saveState()
                c.translate(cx, cy)
                c.scale(squeeze, 1.0)
                c.drawCentredString(0, 0, tok)
                c.restoreState()
            else:
                c.drawCentredString(cx, cy, tok)


def header(c, title, meta, page_no, total_pages, x0, grid_w, cols, cell):
    """画页眉，返回格子区的顶部 y 坐标。"""
    y = PH - 42
    c.setFillColorRGB(*TEXT_BLACK)
    c.setFont("Kai", 13)
    name = title if title else "申论答题纸"
    if page_no > 1:
        name = name + "（续）"
    c.drawCentredString(x0 + grid_w / 2.0, y, name)

    y -= 17
    c.setFont("Kai", 9.5)
    c.setFillColorRGB(*HEAD_GRAY)
    left = meta if meta else ""
    right = "%d格 × %d行/页" % (cols, 0)
    if left:
        c.drawCentredString(x0 + grid_w / 2.0, y, left)

    y -= 9
    c.setStrokeColorRGB(*GRID_GRAY)
    c.setLineWidth(0.6)
    c.line(x0, y, x0 + grid_w, y)
    return PH - HEADER_H


def footer(c, page_no, total_pages, x0, grid_w):
    y = 34
    c.setFont("Kai", 8.5)
    c.setFillColorRGB(*LIGHT_GRAY)
    c.drawCentredString(x0 + grid_w / 2.0, y, "第 %d 页 / 共 %d 页" % (page_no, total_pages))
    c.setFont("Kai", 7.5)
    c.drawString(x0, y, "申论答题纸")
    c.drawRightString(x0 + grid_w, y, "每字一格 · 换行废格已计入")


def render_question(c, q, font_ready, page_counter):
    cols = q.get("cols", 25)
    cell = q.get("cell", 20.0)
    doc_mode = q.get("doc_mode", "none")
    indent = q.get("indent", 0)
    limit = q.get("limit", 0)
    approx = q.get("approx", False)

    res = layout_grid(q["text"], cols=cols, indent=indent, doc_mode=doc_mode, include_rows=True)
    res = _apply_limit(res, limit, "approx" if approx else "strict")
    rows = res.get("rows", [])
    roles = res.get("row_roles", [])

    need_rows = len(rows)
    if limit > 0:
        need_rows = max(need_rows, (limit + cols - 1) // cols)
    if need_rows == 0:
        need_rows = 1

    grid_w = cols * cell
    x0 = (PW - grid_w) / 2.0
    rows_per_page = max(1, int((PH - HEADER_H - BOTTOM_RESERVED) // cell))
    pages = (need_rows + rows_per_page - 1) // rows_per_page

    for p in range(pages):
        start = p * rows_per_page
        chunk = rows[start:start + rows_per_page]
        chunk_roles = roles[start:start + rows_per_page]
        y_after_header = header(c, q.get("title", ""), q.get("meta", ""), p + 1, pages, x0, grid_w, cols, cell)
        n_draw = min(rows_per_page, need_rows - start)
        draw_grid(c, x0, y_after_header, cols, n_draw, cell)
        draw_cells(c, x0, y_after_header, chunk, chunk_roles, cols, cell, cell * 0.74, start)

        c.setFont("Kai", 7.5)
        c.setFillColorRGB(*LIGHT_GRAY)
        for j in range(n_draw):
            if (start + j + 1) % 5 == 0:
                cum = (start + j + 1) * cols
                yy = y_after_header - (j + 1) * cell + cell * 0.3
                c.drawRightString(x0 + grid_w + 16, yy, str(cum))
        footer(c, p + 1, pages, x0, grid_w)
        c.showPage()

    return res


def main():
    ap = argparse.ArgumentParser(description="生成填写好答案的申论答题纸 PDF")
    ap.add_argument("-f", "--file", help="答案文本文件（UTF-8）")
    ap.add_argument("--text", help="直接传入答案文本")
    ap.add_argument("-t", "--title", default="", help="题目标题，如「第一题 归纳概括」")
    ap.add_argument("-m", "--meta", default="", help="副标题，如「10分｜不超过250字」")
    ap.add_argument("-l", "--limit", type=int, default=0, help="字数上限（0=不检查）")
    ap.add_argument("--cols", "-w", type=int, default=25, help="每行格数，默认 25")
    ap.add_argument("--cell", type=float, default=20.0, help="格子边长(pt)，默认 20")
    ap.add_argument("--doc-mode", default="none",
                    choices=["none", "essay", "gongwen", "gongwen-speech", "gongwen-full"])
    ap.add_argument("-i", "--indent", type=int, default=0, help="段首缩进格数")
    ap.add_argument("--approx", action="store_true", help="字数要求为「左右」时加上")
    ap.add_argument("--manifest", help="多题目 JSON 清单")
    ap.add_argument("-o", "--out", default="答题纸.pdf", help="输出 PDF 路径")
    ap.add_argument("--font", help="楷体字体路径")
    args = ap.parse_args()

    font_name = register(pick_font(args.font))

    questions = []
    if args.manifest:
        with open(args.manifest, encoding="utf-8") as fh:
            manifest = json.load(fh)
        for item in manifest:
            text = item.get("text")
            if not text and item.get("file"):
                base = os.path.dirname(os.path.abspath(args.manifest))
                fp = item["file"]
                if not os.path.isabs(fp) and not os.path.exists(fp):
                    fp = os.path.join(base, fp)
                with open(fp, encoding="utf-8") as fh:
                    text = fh.read()
            if not text:
                raise SystemExit("清单条目缺少 text/file：" + json.dumps(item, ensure_ascii=False))
            item = dict(item)
            item["text"] = text
            questions.append(item)
    else:
        if args.text is not None:
            text = args.text
        elif args.file:
            with open(args.file, encoding="utf-8") as fh:
                text = fh.read()
        else:
            text = sys.stdin.read()
        questions.append({
            "text": text, "title": args.title, "meta": args.meta, "limit": args.limit,
            "cols": args.cols, "cell": args.cell, "doc_mode": args.doc_mode,
            "indent": args.indent, "approx": args.approx,
        })

    c = rl_canvas.Canvas(args.out, pagesize=A4)
    c.setTitle(os.path.basename(args.out))
    reports = []
    for q in questions:
        reports.append(render_question(c, q, True, 0))
    c.save()

    out = [{
        "title": q.get("title", ""),
        "summary": r.get("summary", ""),
        "status": r.get("status", ""),
        "rows": r.get("total_rows"),
        "cells": r.get("total_grid_cells_consumed"),
        "notes": r.get("advice_notes", ""),
        "advice": [a["tip"] for a in r.get("advice", [])],
    } for q, r in zip(questions, reports)]
    print(json.dumps({"pdf": os.path.abspath(args.out), "questions": out}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
