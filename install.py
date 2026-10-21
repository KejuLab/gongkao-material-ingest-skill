#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""跨平台安装脚本：把本仓库的 skill 复制到目标技能目录。

只依赖 Python 标准库，可在安装第三方依赖之前运行。

用法：
    python install.py                                  # 交互式选择
    python install.py --tool cursor --scope project    # 装到当前项目的 .agents/skills/
    python install.py --tool cursor --scope user       # 装到 ~/.cursor/skills/
    python install.py --target ~/my-skills/gongkao-material-ingest
    python install.py --dry-run ...                    # 只看会做什么，不写文件
    python install.py ... --with-deps                  # 顺便 pip install -r requirements.txt
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

DEFAULT_SKILL_NAME = "gongkao-material-ingest"

# (工具, 作用域) -> 技能目录（作用域为 project 时相对于项目根）
TOOL_PATHS = {
    ("cursor", "project"): ".agents/skills",
    ("cursor", "user"): "~/.cursor/skills",
    ("claude", "project"): ".claude/skills",
    ("claude", "user"): "~/.claude/skills",
    ("codex", "project"): ".codex/skills",
    ("codex", "user"): "~/.codex/skills",
    ("generic", "project"): ".agents/skills",
    ("generic", "user"): "~/.agents/skills",
}

TOOL_NAMES = ("cursor", "claude", "codex", "generic")

if hasattr(sys.stdout, "reconfigure"):
    try:  # 让中文在 Windows 终端里也能正常显示
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def say(msg: str = "") -> None:
    try:
        print(msg)
    except UnicodeEncodeError:  # 某些 Windows 控制台
        print(msg.encode("ascii", "replace").decode("ascii"))


def read_skill_name(skill_md: Path) -> str:
    text = skill_md.read_text(encoding="utf-8")
    m = re.search(r"^---\s*$(.*?)^---\s*$", text, re.S | re.M)
    if not m:
        return ""
    fm = re.search(r"^name:\s*(.+)$", m.group(1), re.M)
    return fm.group(1).strip().strip("\"'") if fm else ""


def resolve_target(tool: str, scope: str, project_dir: Path, raw_target: str | None, name: str) -> Path:
    if raw_target:
        p = Path(os.path.expandvars(os.path.expanduser(raw_target)))
        if not p.is_absolute():
            p = (Path.cwd() / p).resolve()
        if p.name != name:
            say("提示：目标文件夹名与技能名不一致，已自动补成 %s/" % name)
            p = p / name
        return p
    if (tool, scope) not in TOOL_PATHS:
        raise SystemExit("不支持的组合：%s / %s" % (tool, scope))
    base = TOOL_PATHS[(tool, scope)]
    if scope == "project":
        return (project_dir / base / name).resolve()
    return Path(os.path.expanduser(base)) / name


def plan_copy(repo: Path, dest: Path) -> list[tuple[Path, Path]]:
    pairs = [(repo / "SKILL.md", dest / "SKILL.md")]
    scripts = sorted((repo / "scripts").glob("*.py"))
    if not scripts:
        raise SystemExit("仓库里找不到 scripts/*.py，请在仓库根目录运行本脚本")
    for src in scripts:
        pairs.append((src, dest / "scripts" / src.name))
    return pairs


def main() -> int:
    ap = argparse.ArgumentParser(description="把本仓库的 skill 安装到目标技能目录")
    ap.add_argument("--tool", choices=TOOL_NAMES, help="目标工具（默认交互选择）")
    ap.add_argument("--scope", choices=("project", "user"), help="项目级或用户级（默认交互选择）")
    ap.add_argument("--target", help="直接指定目标目录（忽略 --tool/--scope）")
    ap.add_argument("--project-dir", default=".", help="项目根目录，默认当前目录")
    ap.add_argument("--with-deps", action="store_true", help="顺带执行 pip install -r requirements.txt")
    ap.add_argument("--force", action="store_true", help="目标目录有无关文件时也覆盖")
    ap.add_argument("--dry-run", action="store_true", help="只打印计划，不写文件")
    args = ap.parse_args()

    repo = Path(__file__).resolve().parent
    skill_md = repo / "SKILL.md"
    if not skill_md.exists():
        say("找不到 SKILL.md，请在仓库根目录运行本脚本。")
        return 2

    name = read_skill_name(skill_md) or DEFAULT_SKILL_NAME
    if name != DEFAULT_SKILL_NAME:
        say("注意：SKILL.md 的 name 是 %r，将按它创建目录。" % name)
    if "/" in name or "\\" in name:
        say("SKILL.md 的 name 不合法（不能含路径分隔符）。")
        return 2

    tool, scope = args.tool, args.scope
    if not args.target and (not tool or not scope):
        say("请选择安装位置：")
        say("  1) Cursor · 项目级  (%s)" % TOOL_PATHS[("cursor", "project")])
        say("  2) Cursor · 用户级  (%s)" % TOOL_PATHS[("cursor", "user")])
        say("  3) Claude Code · 用户级  (%s)" % TOOL_PATHS[("claude", "user")])
        say("  4) Codex · 用户级  (%s)" % TOOL_PATHS[("codex", "user")])
        say("  5) 其他（手动给 --target）")
        try:
            choice = input("输入序号 [1]: ").strip() or "1"
        except EOFError:
            say("非交互环境，请用 --tool/--scope 或 --target 指定。")
            return 2
        presets = {
            "1": ("cursor", "project"),
            "2": ("cursor", "user"),
            "3": ("claude", "user"),
            "4": ("codex", "user"),
        }
        if choice == "5":
            say("请用 --target 指定目标目录，例如：")
            say("  python install.py --target ~/skills/%s" % name)
            return 1
        tool, scope = presets.get(choice, ("cursor", "project"))

    dest = resolve_target(tool, scope, Path(args.project_dir).resolve(), args.target, name)
    pairs = plan_copy(repo, dest)

    # 安全检查：目标已存在且含无关文件时，要求 --force
    if dest.exists() and not args.force:
        existing = {p.name for p in dest.iterdir()}
        allowed = {"SKILL.md", "scripts"}
        extra = existing - allowed
        if extra:
            say("目标目录已有其他文件：%s" % ", ".join(sorted(extra)))
            say("确认要装到这里请加 --force，或换一个 --target。")
            if not args.dry_run:
                return 1

    say("仓库：%s" % repo)
    say("目标：%s" % dest)
    say("技能名：%s" % name)
    for src, dst in pairs:
        say("  %s -> %s" % (src.relative_to(repo), dst.relative_to(dest) if dst != dest else "."))

    if args.dry_run:
        say("\n[dry-run] 未写入任何文件。")
        return 0

    dest.mkdir(parents=True, exist_ok=True)
    (dest / "scripts").mkdir(exist_ok=True)
    for src, dst in pairs:
        shutil.copy2(src, dst)
    say("\n已安装 %d 个文件。" % len(pairs))

    if args.with_deps:
        req = repo / "requirements.txt"
        if req.exists():
            say("\n安装依赖：%s -m pip install -r %s" % (sys.executable, req))
            subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", str(req)])
    else:
        say("依赖还没装的话，执行：pip install -r requirements.txt")

    say("\n下一步：重开窗口（或 Developer: Reload Window）让工具重新发现技能。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
