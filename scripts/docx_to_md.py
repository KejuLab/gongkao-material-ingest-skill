#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""docx -> Markdown，保持段落顺序，并把内嵌图片（课件截图）就地抽出来插回原位。

用法:
    python docx_to_md.py "AI总结.docx" -o out.md --imgdir out-images
"""
import argparse
import os
import re
import zipfile
import xml.etree.ElementTree as ET

NS = {
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "pr": "http://schemas.openxmlformats.org/package/2006/relationships",
    "wp": "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing",
}


def q(tag):
    p, t = tag.split(":")
    return "{%s}%s" % (NS[p], t)


def load_rels(z):
    rels = {}
    name = "word/_rels/document.xml.rels"
    if name not in z.namelist():
        return rels
    root = ET.fromstring(z.read(name))
    for rel in root:
        rels[rel.get("Id")] = rel.get("Target")
    return rels


def para_text(p):
    parts = []
    for node in p.iter():
        tag = node.tag
        if tag == q("w:t"):
            parts.append(node.text or "")
        elif tag == q("w:tab"):
            parts.append("\t")
        elif tag == q("w:br"):
            parts.append("\n")
    return "".join(parts)


def para_images(p, rels):
    out = []
    for blip in p.iter(q("a:blip")):
        rid = blip.get(q("r:embed"))
        if rid and rid in rels:
            out.append(rels[rid])
    return out


def para_style(p):
    ppr = p.find(q("w:pPr"))
    if ppr is None:
        return None, False
    ps = ppr.find(q("w:pStyle"))
    style = ps.get(q("w:val")) if ps is not None else None
    numbered = ppr.find(q("w:numPr")) is not None
    return style, numbered


def para_bold(p):
    runs = [r for r in p.iter(q("w:r"))]
    if not runs:
        return False
    tot = 0
    bold = 0
    for r in runs:
        t = "".join(n.text or "" for n in r.iter(q("w:t")))
        if not t.strip():
            continue
        tot += 1
        rpr = r.find(q("w:rPr"))
        if rpr is not None and rpr.find(q("w:b")) is not None:
            bold += 1
    return tot > 0 and bold == tot


STYLE_LEVEL = {
    "title": 1,
    "heading1": 1,
    "heading2": 2,
    "heading3": 3,
    "heading4": 4,
    "heading5": 5,
    "heading6": 6,
    "1": 1,
    "2": 2,
    "3": 3,
    "4": 4,
    # 中文样式名（WPS / 夸克常见）
    "全文一级大标题": 1,
    "正文一级标题": 2,
    "正文二级标题": 3,
    "正文三级标题": 4,
    "正文四级标题": 5,
}

STYLE_LIST = {
    "一级无序列表": "- ",
    "二级无序列表": "- ",
    "一级有序列表": "1. ",
    "二级有序列表": "1. ",
}


def table_md(tbl):
    rows = []
    for tr in tbl.findall(q("w:tr")):
        cells = []
        for tc in tr.findall(q("w:tc")):
            txt = " ".join(para_text(p).strip() for p in tc.findall(q("w:p"))).strip()
            cells.append(txt.replace("|", "\\|"))
        rows.append(cells)
    if not rows:
        return ""
    width = max(len(r) for r in rows)
    rows = [r + [""] * (width - len(r)) for r in rows]
    lines = ["| " + " | ".join(rows[0]) + " |", "|" + "---|" * width]
    for r in rows[1:]:
        lines.append("| " + " | ".join(r) + " |")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("docx")
    ap.add_argument("-o", "--out", required=True)
    ap.add_argument("--imgdir", default=None, help="图片输出目录（默认 out 同级的 images）")
    args = ap.parse_args()

    outdir = os.path.dirname(os.path.abspath(args.out)) or "."
    imgdir = args.imgdir or os.path.join(outdir, "images")
    os.makedirs(outdir, exist_ok=True)
    os.makedirs(imgdir, exist_ok=True)

    z = zipfile.ZipFile(args.docx)
    root = ET.fromstring(z.read("word/document.xml"))
    rels = load_rels(z)
    body = root.find(q("w:body"))

    written_images = {}
    unknown_styles = {}
    lines = []
    para_count = 0
    img_count = 0

    for child in body:
        if child.tag == q("w:p"):
            text = para_text(child).strip()
            style, numbered = para_style(child)
            imgs = para_images(child, rels)
            level = STYLE_LEVEL.get((style or "").lower())
            listmark = STYLE_LIST.get(style or "")
            if style and not level and not listmark:
                unknown_styles[style] = unknown_styles.get(style, 0) + 1
            if text:
                para_count += 1
                if level:
                    lines.append("")
                    lines.append("#" * level + " " + re.sub(r"\s+", " ", text))
                    lines.append("")
                elif listmark:
                    lines.append(listmark + text)
                elif numbered:
                    lines.append("- " + text)
                elif para_bold(child) and len(text) <= 30 and not text.endswith(("。", "：")):
                    lines.append("")
                    lines.append("**" + text + "**")
                    lines.append("")
                else:
                    lines.append(text)
                    lines.append("")
            for target in imgs:
                src = "word/" + target.replace("\\", "/")
                if src not in z.namelist():
                    src = target.lstrip("/")
                    if src not in z.namelist():
                        continue
                base = os.path.basename(src)
                if base not in written_images:
                    dst = os.path.join(imgdir, base)
                    with open(dst, "wb") as f:
                        f.write(z.read(src))
                    written_images[base] = dst
                    img_count += 1
                rel = os.path.relpath(written_images[base], outdir).replace("\\", "/")
                lines.append("![](%s)" % rel)
                lines.append("")
        elif child.tag == q("w:tbl"):
            md = table_md(child)
            if md:
                lines.append("")
                lines.append(md)
                lines.append("")

    text = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip() + "\n"
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(text)
    print("paragraphs:", para_count, "| images:", img_count, "| out chars:", len(text))
    if unknown_styles:
        print("unknown styles:", unknown_styles)
    print("written:", args.out, "| images:", imgdir)


if __name__ == "__main__":
    main()
