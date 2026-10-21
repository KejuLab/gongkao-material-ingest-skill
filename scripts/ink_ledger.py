#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""平板批改 PDF -> 作答台账（题号 / 划掉的选项 / 手写字母 / 划线重点 / 疑点）

原理：平板导出的 PDF 通常是「原页图像 + 正文文本层 + 一整页带透明通道的笔迹图层」。
本脚本取出笔迹层的 alpha 通道（=笔迹本身）与 RGB（=笔的颜色），
把每一笔按颜色（黑/红/蓝）与形状（划线/斜线/字母/圈）分类，
再按坐标映射回文本行与题目，输出机读 JSON、人读 Markdown 和字母拼版图。

用法:
    python ink_ledger.py "批改.pdf" -o out_dir
    python ink_ledger.py "批改.pdf" -o out_dir --answers out_dir/answers.csv
"""
import argparse
import collections
import csv
import json
import os
import re
import shutil
import sys

import numpy as np
import pymupdf
from scipy import ndimage

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:  # pragma: no cover
    Image = None

Q_START = re.compile(r"^(?:例题\s*\d+|【例\s*\d+】?)")
OPT_LETTERS = "ABCD"


# ---------------------------------------------------------------- ink layers
def ink_layers(doc, page):
    """返回 (rgb[H,W,3], alpha[H,W], scale_x, scale_y)；无笔迹层返回 None。"""
    xref = None
    for info in page.get_image_info(xrefs=True):
        if info["bbox"][0] <= 1 and info["bbox"][1] <= 1:
            xref = info["xref"]
    if xref is None:
        return None
    obj = doc.xref_object(xref)
    m = re.search(r"/SMask\s+(\d+)", obj)
    if not m:
        return None
    rgb = pymupdf.Pixmap(doc, xref)
    alpha = pymupdf.Pixmap(doc, int(m.group(1)))
    ra = np.frombuffer(rgb.samples, dtype=np.uint8).reshape(rgb.height, rgb.width, rgb.n)
    ra = ra[:, :, :3]
    al = np.frombuffer(alpha.samples, dtype=np.uint8).reshape(alpha.height, alpha.width, alpha.n)
    al = al[:, :, 0]
    return ra, al, page.rect.width / rgb.width, page.rect.height / rgb.height


def color_of(rgb, mask):
    r, g, b = np.median(rgb[mask], axis=0)
    if r > 110 and g < 110 and b < 110:
        return "red"
    if b > 110 and r < 110:
        return "blue"
    if max(r, g, b) < 110:
        return "black"
    if r > 200 and g > 200 and b > 200:
        return "faint"
    return "other"


def stroke_features(mask, sl):
    """返回 (elongation, 笔画宽度)。elongation 大 = 一条线（划线/斜线）。"""
    m = np.zeros(mask.shape, bool)
    m[sl] = mask[sl]
    ys, xs = np.nonzero(m)
    if len(xs) < 10:
        return 0.0, 0.0
    cov = np.cov(np.vstack([xs, ys]))
    ev = np.linalg.eigvalsh(cov)
    elong = float(ev[1] / max(ev[0], 1e-6))
    sub = m[sl]
    dt = ndimage.distance_transform_edt(sub)
    stroke = 2 * float(dt.max())
    return elong, stroke


def shape_of(w, h, density, elong, stroke):
    if elong > 20 and h <= 16 and w >= 25:
        return "underline"
    if elong > 20 and (h > 16 or w <= 20):
        return "slash"
    if w >= 120 and h >= 120 and density <= 0.12:
        return "circle"
    if elong <= 20 and h >= 28 and w >= 15 and density <= 0.4:
        return "letter"
    return "mark"


# ---------------------------------------------------------------- text model
def page_lines(page):
    """行级文本；(bbox, text, size)"""
    out = []
    for b in page.get_text("dict")["blocks"]:
        for l in b.get("lines", []):
            t = "".join(s["text"] for s in l["spans"])
            if not t.strip():
                continue
            size = max(round(s["size"], 1) for s in l["spans"] if s["text"].strip()) if l["spans"] else 0
            out.append({"bbox": pymupdf.Rect(l["bbox"]), "text": t.strip(), "flat": re.sub(r"\s+", "", t), "size": size})
    return out


def option_markers(page):
    """在行内定位 A．/B．/C．/D． 标记，返回 [(letter, rect, text)]"""
    opts = []
    d = page.get_text("rawdict")
    for b in d["blocks"]:
        for l in b.get("lines", []):
            chars = []
            for s in l["spans"]:
                for c in s.get("chars", []):
                    chars.append(c)
            if not chars:
                continue
            chars.sort(key=lambda c: c["bbox"][0])
            idx = []
            for i, c in enumerate(chars[:-1]):
                ch = c["c"]
                nxt = chars[i + 1]["c"]
                if ch in OPT_LETTERS and nxt in "．.、":
                    # 排除句中小写引用：A 前不能是汉字/字母
                    if i > 0 and (chars[i - 1]["c"].isalnum() and ord(chars[i - 1]["c"]) > 127):
                        continue
                    idx.append(i)
            for k, i in enumerate(idx):
                x0 = chars[i]["bbox"][0]
                x1 = chars[idx[k + 1]]["bbox"][0] if k + 1 < len(idx) else chars[-1]["bbox"][2]
                y0 = min(c["bbox"][1] for c in chars[i:(idx[k + 1] if k + 1 < len(idx) else len(chars))])
                y1 = max(c["bbox"][3] for c in chars[i:(idx[k + 1] if k + 1 < len(idx) else len(chars))])
                txt = "".join(c["c"] for c in chars[i:(idx[k + 1] if k + 1 < len(idx) else len(chars))]).strip()
                txt = re.sub(r"^[A-D][．.、]\s*", "", txt)
                opts.append({"letter": chars[i]["c"], "rect": pymupdf.Rect(x0, y0, x1, y1), "text": txt})
    return opts


def build_questions(pages_lines, page_count):
    """按 例题/【例 N】 切分题目，返回 questions 与边界表。"""
    starts = []
    for pno, lines in enumerate(pages_lines, start=1):
        for ln in lines:
            if Q_START.match(ln["flat"]):
                starts.append((pno, ln["bbox"].y0, ln["flat"][:30]))
    questions = []
    for i, (pno, y0, label) in enumerate(starts):
        if i + 1 < len(starts):
            end = (starts[i + 1][0], starts[i + 1][1])
        else:
            end = (page_count, 1e9)
        questions.append({"id": i + 1, "label": label, "start": (pno, y0), "end": end,
                          "page": pno, "ask": "", "options": {}, "eliminated": [],
                          "black_letters": [], "red_letters": [], "blue": [], "underlines": [],
                          "blobs": []})
    return questions


def locate(questions, page, y):
    """(page, y) -> question id（阅读顺序上最近的前一个题目起点）"""
    best = None
    for q in questions:
        s, e = q["start"], q["end"]
        if (page, y) >= s and (page, y) < e:
            return q["id"]
        if (page, y) >= s:
            best = q["id"]
    return best


def fill_text(questions, pages_lines, pages_opts):
    for pno, lines in enumerate(pages_lines, start=1):
        for ln in lines:
            qid = locate(questions, pno, ln["bbox"].y0)
            if qid is None:
                continue
            q = questions[qid - 1]
            if re.search(r"(这段文字|下列|填入|最适合|依次填入|接下来|语序|不相符|理解错误|意在|主旨|概括)", ln["flat"]):
                if not q["ask"]:
                    q["ask"] = ln["text"]
        for o in pages_opts.get(pno, []):
            qid = locate(questions, pno, o["rect"].y0)
            if qid is None:
                continue
            q = questions[qid - 1]
            q["options"].setdefault(o["letter"], o["text"])


def save_crop(page, rect, path, dpi=260, pad=6):
    if Image is None:
        return False
    clip = pymupdf.Rect(rect.x0 - pad, rect.y0 - pad, rect.x1 + pad, rect.y1 + pad)
    clip = clip & page.rect
    pix = page.get_pixmap(clip=clip, dpi=dpi)
    pix.save(path)
    return True


def montage(items, out_path, cols=6, cell=(200, 170), font_path=None):
    """items: [(label, png_path)]"""
    rows = (len(items) + cols - 1) // cols
    W, H = cols * cell[0], rows * cell[1]
    sheet = Image.new("RGB", (W, H), "white")
    draw = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.truetype(font_path or "arial.ttf", 14)
    except Exception:
        font = ImageFont.load_default()
    for i, (label, png) in enumerate(items):
        cx, cy = (i % cols) * cell[0], (i // cols) * cell[1]
        draw.rectangle([cx, cy, cx + cell[0] - 1, cy + cell[1] - 1], outline=(190, 190, 190))
        draw.text((cx + 4, cy + 2), label, fill=(180, 0, 0), font=font)
        try:
            im = Image.open(png).convert("RGB")
            im.thumbnail((cell[0] - 8, cell[1] - 26))
            sheet.paste(im, (cx + (cell[0] - im.width) // 2, cy + 22))
        except Exception:
            pass
    sheet.save(out_path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf")
    ap.add_argument("-o", "--out", required=True)
    ap.add_argument("--answers", default=None, help="csv: id,letter")
    ap.add_argument("--min-area", type=int, default=25)
    args = ap.parse_args()

    doc = pymupdf.open(args.pdf)
    outdir = os.path.abspath(args.out)
    cropdir = os.path.join(outdir, "crops")
    mdir = os.path.join(outdir, "montage")
    for d in (cropdir, mdir):  # 清掉上一次的产物，避免张冠李戴
        if os.path.isdir(d):
            shutil.rmtree(d, ignore_errors=True)
    for d in (outdir, cropdir, mdir):
        os.makedirs(d, exist_ok=True)

    pages_lines = [page_lines(doc[p]) for p in range(doc.page_count)]
    pages_opts = {p + 1: option_markers(doc[p]) for p in range(doc.page_count)}
    questions = build_questions(pages_lines, doc.page_count)
    fill_text(questions, pages_lines, pages_opts)

    blobs = []
    per_page_ink = {}
    for pno in range(doc.page_count):
        page = doc[pno]
        layers = ink_layers(doc, page)
        if not layers:
            continue
        rgb, alpha, sx, sy = layers
        mask = alpha > 180
        if mask.sum() < 150:
            continue
        per_page_ink[pno + 1] = int(mask.sum())
        lab, n = ndimage.label(mask)
        for k, sl in enumerate(ndimage.find_objects(lab)):
            sub = mask[sl]
            area = int(sub.sum())
            if area < args.min_area:
                continue
            y0, y1 = sl[0].start, sl[0].stop
            x0, x1 = sl[1].start, sl[1].stop
            w, h = x1 - x0, y1 - y0
            density = area / max(w * h, 1)
            color = color_of(rgb[sl], sub)
            elong, stroke = stroke_features(mask, sl)
            shape = shape_of(w, h, density, elong, stroke)
            rect = pymupdf.Rect(x0 * sx, y0 * sy, x1 * sx, y1 * sy)
            qid = locate(questions, pno + 1, rect.y0)
            blob = {"id": "p%02d#%02d" % (pno + 1, k + 1), "page": pno + 1, "color": color,
                    "shape": shape, "bbox": [round(rect.x0, 1), round(rect.y0, 1), round(rect.x1, 1), round(rect.y1, 1)],
                    "area": area, "density": round(density, 3), "elong": round(elong, 1),
                    "stroke": round(stroke, 1), "question": qid, "text": "",
                    "px": [int(x0), int(y0), int(x1), int(y1)]}
            if qid:
                questions[qid - 1]["blobs"].append(blob["id"])
            blobs.append(blob)

    # 映射到文本行 / 选项
    for blob in blobs:
        pno = blob["page"]
        rect = pymupdf.Rect(blob["bbox"])
        best, bov = None, 0
        for ln in pages_lines[pno - 1]:
            lr = ln["bbox"]
            ov = max(0, min(lr.x1, rect.x1) - max(lr.x0, rect.x0))
            voy = max(0, min(lr.y1 + 4, rect.y1) - max(lr.y0 - 4, rect.y0))
            score = ov * (voy + 1)
            if score > bov:
                bov, best = score, ln
        if best:
            blob["text"] = best["text"][:120]
        # 选项命中（只有斜线才算划掉；下划线是重点标记）
        if blob["shape"] == "slash":
            for o in pages_opts.get(pno, []):
                inter = (o["rect"] & rect).get_area()
                if inter > 0.25 * max(rect.get_area(), 1):
                    if blob["question"]:
                        q = questions[blob["question"] - 1]
                        if o["letter"] not in q["eliminated"]:
                            q["eliminated"].append(o["letter"])
                    blob["option"] = o["letter"]
                    break

    # 颜色 -> 语义
    letter_items = []
    composites = {}

    def composite(pno):
        if pno not in composites:
            r, a2, _, _ = ink_layers(doc, doc[pno - 1])
            hh, ww = a2.shape
            canvas = np.full((hh, ww, 3), 255, np.uint8)
            mm = a2 > 60
            canvas[mm] = r[mm]
            composites[pno] = Image.fromarray(canvas)
        return composites[pno]

    for blob in blobs:
        qid = blob["question"]
        if not qid:
            continue
        q = questions[qid - 1]
        if blob["shape"] == "letter":
            if blob["color"] == "black":
                q["black_letters"].append(blob["id"])
            elif blob["color"] == "red":
                q["red_letters"].append(blob["id"])
            elif blob["color"] == "blue":
                q["blue"].append(blob["id"])
            else:
                q["blue"].append(blob["id"])
            fn = os.path.join(cropdir, "%s.png" % blob["id"].replace("#", "_"))
            x0, y0, x1, y1 = blob["px"]
            pad = 10
            im = composite(blob["page"]).crop((max(0, x0 - pad), max(0, y0 - pad), x1 + pad, y1 + pad))
            im = im.resize((max(1, int(im.width * 2.2)), max(1, int(im.height * 2.2))), Image.LANCZOS)
            im.save(fn)
            letter_items.append(("#" + blob["id"], fn))
            blob["crop"] = os.path.relpath(fn, outdir).replace("\\", "/")
        elif blob["shape"] == "underline" and blob["text"]:
            q["underlines"].append(blob["text"])
        elif blob["color"] == "blue":
            q["blue"].append(blob["id"])

    # 拼版图
    sheets = []
    chunk = 30
    for i in range(0, len(letter_items), chunk):
        fp = os.path.join(mdir, "sheet-%02d.png" % (i // chunk + 1))
        montage(letter_items[i:i + chunk], fp)
        sheets.append(fp)

    # 合并人工识别的字母
    answers = {}
    if args.answers and os.path.exists(args.answers):
        with open(args.answers, encoding="utf-8-sig") as f:
            for row in csv.reader(f):
                if len(row) >= 2 and row[0].strip():
                    answers[row[0].strip().lstrip("#")] = row[1].strip().upper()

    data = {"source": os.path.basename(args.pdf), "pages": doc.page_count,
            "ink_pages": len(per_page_ink), "blobs": blobs,
            "shape_stats": dict(collections.Counter(b["shape"] for b in blobs)),
            "color_stats": dict(collections.Counter(b["color"] for b in blobs)),
            "questions": questions, "sheets": [os.path.basename(s) for s in sheets]}
    with open(os.path.join(outdir, "ink-ledger.json"), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)

    # 人读台账
    L = []
    L.append("# 作答台账：%s" % data["source"])
    L.append("")
    L.append("页数 %d｜有笔迹 %d 页｜笔迹块 %d（%s）｜颜色 %s" % (
        doc.page_count, data["ink_pages"], len(blobs),
        "、".join("%s %d" % (k, v) for k, v in data["shape_stats"].items()),
        "、".join("%s %d" % (k, v) for k, v in data["color_stats"].items())))
    L.append("")
    stat = collections.Counter()
    L.append("| 题目 | 页 | 提问 | 划掉 | 黑笔(原始) | 红笔(批改) | 判定 | 备注 |")
    L.append("| --- | --- | --- | --- | --- | --- | --- | --- |")
    for q in questions:
        if len(q["options"]) < 2:
            continue

        def letters(ids):
            return "".join(sorted({answers.get(i, "?") for i in ids} - {"-", ""})) or ""

        black, red = letters(q["black_letters"]), letters(q["red_letters"])
        note = ""
        if black and red and set(black) != set(red):
            verdict = "错→%s" % red
            stat["wrong"] += 1
        elif red and not black:
            verdict = "红%s" % red
            stat["red_only"] += 1
        elif black and not red:
            verdict = "黑%s" % black
            stat["assumed_ok"] += 1
        else:
            verdict = ""
            stat["unknown"] += 1
        if black and black[0] in q["eliminated"]:
            note = "答在划掉项上"
            stat["conflict"] += 1
        if len(q["options"]) and len(q["eliminated"]) >= 3:
            rest = [k for k in sorted(q["options"]) if k not in q["eliminated"]]
            if rest:
                note = (note + "｜" if note else "") + "排除法=%s" % rest[0]
        L.append("| %s | %d | %s | %s | %s | %s | %s | %s |" % (
            q["label"], q["page"], (q["ask"] or "")[:18],
            "".join(q["eliminated"]), black, red, verdict, note))
    L.insert(4, "题目 %d｜判错 %d｜补答 %d｜未见批改 %d｜可疑 %d" % (
        sum(stat[k] for k in ("wrong", "red_only", "assumed_ok", "unknown")),
        stat["wrong"], stat["red_only"], stat["assumed_ok"], stat["conflict"]))
    L.insert(5, "")
    recognized = sum(1 for _, fn in letter_items if os.path.basename(fn).replace(".png", "").replace("_", "#") in answers)
    L.append("")
    L.append("字母待识别：%d 个（已识别 %d），拼版图在 `montage/`（每格标 #id 与页码），识别结果写进 `answers.csv`（两列 id,letter）后加 `--answers` 重跑。" % (
        len(letter_items) - recognized, recognized))
    with open(os.path.join(outdir, "ink-ledger.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")

    print("pages:", doc.page_count, "| ink pages:", len(per_page_ink))
    print("blobs:", len(blobs), data["shape_stats"], data["color_stats"])
    print("questions:", len(questions), "| letter crops:", len(letter_items), "| sheets:", len(sheets))
    print("written:", outdir)


if __name__ == "__main__":
    main()
