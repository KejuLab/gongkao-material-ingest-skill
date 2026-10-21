#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""讲义 PDF -> 结构化 Markdown

按字号 + 文字规律重建标题层级，剔除重复页眉页脚与目录点线，合并断行成段，
并把挤在同一行的多个选项（如「A．xx B．yy」）拆成独立行。

用法:
    python pdf_structure.py "讲义.pdf" -o out.md [--no-page-marks]
"""
import argparse
import collections
import os
import re

import pymupdf


HEAD_PATTERNS = [
    (re.compile(r"^第[一二三四五六七八九十]+部分"), 1),
    (re.compile(r"^第[一二三四五六七八九十]+章"), 2),
    (re.compile(r"^\d+\.\d+\.\d+"), 4),
    (re.compile(r"^\d+\.\d+(?!\d)"), 3),
    (re.compile(r"^[一二三四五六七八九十]+、"), 4),
    (re.compile(r"^（[一二三四五六七八九十]+）"), 5),
    (re.compile(r"^【例\s*\d+】"), 5),
    (re.compile(r"^例题\s*\d+"), 5),
]

TOC_LINE = re.compile(r"(\.{4,}|…{2,})\s*\d+\s*$")
OPT_MARK = re.compile(r"(?<![A-Za-z0-9])[A-D][．.、]")
END_PUNCT = "。！？；：”』）】"


def read_blocks(doc):
    """按块读取，块内按字符坐标还原空格（表格状选项需要）。"""
    pages = []
    for pno in range(doc.page_count):
        page = doc[pno]
        blocks = []
        for b in page.get_text("rawdict")["blocks"]:
            lines = []
            sizes = []
            for l in b.get("lines", []):
                out = []
                prev_x1 = None
                size = 0
                for s in l["spans"]:
                    if s.get("chars"):
                        size = max(size, round(s["size"], 1))
                        sizes.append(round(s["size"], 1))
                    for ch in s.get("chars", []):
                        c = ch["c"]
                        if c in "\n\r":
                            continue
                        if prev_x1 is not None and ch["bbox"][0] - prev_x1 > s["size"] * 0.28:
                            if out and out[-1] != " ":
                                out.append(" ")
                        out.append(c)
                        prev_x1 = ch["bbox"][2]
                text = "".join(out).strip()
                if text:
                    lines.append(text)
            if not lines:
                continue
            joined = "\n".join(lines)
            blocks.append(
                {
                    "text": joined,
                    "flat": re.sub(r"\s+", "", joined),
                    "size": collections.Counter(sizes).most_common(1)[0][0] if sizes else 0,
                    "bbox": b["bbox"],
                    "page": pno + 1,
                }
            )
        pages.append(blocks)
    return pages


def drop_running_heads(pages, doc):
    freq = collections.Counter()
    for blocks in pages:
        for t in {b["flat"] for b in blocks}:
            freq[t] += 1
    threshold = max(3, int(doc.page_count * 0.3))
    repeated = {t for t, c in freq.items() if c >= threshold and len(t) <= 40}
    kept = []
    for blocks, pno in zip(pages, range(1, doc.page_count + 1)):
        ph = doc[pno - 1].rect.height
        out = []
        for b in blocks:
            y0, y1 = b["bbox"][1], b["bbox"][3]
            margin = y0 < ph * 0.09 or y1 > ph * 0.93
            if margin and b["flat"] in repeated:
                continue
            if re.fullmatch(r"第\s*\d+\s*页", b["flat"]):
                continue
            out.append(b)
        kept.append(out)
    return kept


def heading_level(flat, size, body_size):
    for pat, lvl in HEAD_PATTERNS:
        if pat.match(flat):
            return lvl
    if body_size and size >= body_size * 1.35:
        ratio = size / body_size
        return 4 if ratio >= 1.9 else (3 if ratio >= 1.35 else 5)
    return None


def split_options(text):
    """返回拆分后的选项列表；不足两个标记则返回 None。"""
    marks = list(OPT_MARK.finditer(text))
    if len(marks) < 2:
        return None
    if marks[0].start() > 0:
        return None  # 标记不在行首，可能是正文引用
    parts = []
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        parts.append(text[m.start():end].strip())
    return [p for p in parts if p]


def join_lines(prev, cur):
    if not prev:
        return cur
    a, b = prev[-1], cur[0]
    if a.isascii() and a.isalnum() and b.isascii() and b.isalnum():
        return prev + " " + cur
    return prev + cur


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf")
    ap.add_argument("-o", "--out", required=True)
    ap.add_argument("--no-page-marks", action="store_true")
    args = ap.parse_args()

    doc = pymupdf.open(args.pdf)
    pages = drop_running_heads(read_blocks(doc), doc)

    sizes = collections.Counter()
    for blocks in pages:
        for b in blocks:
            sizes[b["size"]] += len(b["flat"])
    body_size = sizes.most_common(1)[0][0] if sizes else 0

    out = []
    stats = collections.Counter()
    buf = ""
    optopen = [False]

    def flush_para():
        nonlocal buf
        if buf:
            out.append(buf)
            out.append("")
            stats["paragraph"] += 1
            buf = ""

    def close_opt():
        if optopen[0]:
            out.append("")
            optopen[0] = False

    def flush():
        flush_para()
        close_opt()

    def emit_option_line(line):
        if not optopen[0]:
            out.append("")
            optopen[0] = True
        out.append(line + "  ")

    for pno, blocks in enumerate(pages, start=1):
        if not args.no_page_marks:
            if optopen[0]:
                out.append("")
                optopen[0] = False
            out.append("<!-- p.%d -->" % pno)
        for b in blocks:
            text = b["text"].strip()
            if not text:
                continue
            flat = b["flat"]
            if TOC_LINE.search(flat):
                stats["toc_dropped"] += 1
                continue
            lvl = heading_level(flat, b["size"], body_size)
            if lvl:
                flush()
                out.append("")
                out.append("#" * min(lvl, 6) + " " + re.sub(r"\s+", " ", text))
                out.append("")
                stats["heading"] += 1
                continue
            opts = split_options(flat)
            if opts and len(opts) >= 2:
                flush_para()
                for o in opts:
                    emit_option_line(o)
                stats["options_split"] += 1
                continue
            if re.match(r"^[A-D][．.、]", text):
                flush_para()
                emit_option_line(re.sub(r"\s*\n\s*", "", text))
                stats["option_line"] += 1
                continue
            close_opt()
            para = re.sub(r"\s*\n\s*", "", text)
            if buf and buf[-1] in END_PUNCT:
                flush()
            buf = join_lines(buf, para)
    flush()

    text = re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip() + "\n"
    os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(text)
    print("pages:", doc.page_count, "| body size:", body_size, "| out chars:", len(text))
    print("blocks:", dict(stats))
    print("written:", args.out)


if __name__ == "__main__":
    main()
