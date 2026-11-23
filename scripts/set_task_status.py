"""把任务的完成状态写进排期表「任务明细」。

进度看板全部由公式驱动（COUNTIF / COUNTIFS / SUMIF / SUMIFS），
唯一需要人工维护的就是「任务明细」的 M 列（状态）。本脚本只改这一列，
不碰任何公式、条件格式、数据验证，所以改完直接重算即可。

用法（在仓库根目录）：

    python scripts/set_task_status.py A01=已完成 A02=已完成
    python scripts/set_task_status.py A03=进行中
    python scripts/set_task_status.py --list          # 看所有任务与当前状态

合法状态：未开始 / 进行中 / 已完成 / 已延期 / 已砍
（与表里的下拉选项一致，写错会被拒绝，避免污染条件格式）

改完记得让 Excel/WPS 重算一次，「进度看板」才会显示新数字；
或者用 office_recalculate 这类工具刷新缓存值。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from openpyxl import load_workbook

DEFAULT_PATH = Path(__file__).resolve().parent.parent / "docs" / "排期表_A_agentloom.xlsx"
STATUS_COL = 13  # M
VALID = {"未开始", "进行中", "已完成", "已延期", "已砍"}
FIRST_DATA_ROW = 4


def collect_rows(ws) -> dict[str, int]:
    """任务 ID -> 行号。按 ID 定位而不是硬编码行号，插入任务时不会错位。"""
    rows: dict[str, int] = {}
    for r in range(FIRST_DATA_ROW, ws.max_row + 1):
        tid = ws.cell(row=r, column=1).value
        if isinstance(tid, str) and tid.strip():
            rows[tid.strip()] = r
    return rows


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="更新排期表任务状态")
    parser.add_argument("changes", nargs="*", help="形如 A01=已完成")
    parser.add_argument("--path", default=str(DEFAULT_PATH), help="排期表路径")
    parser.add_argument("--list", action="store_true", help="列出所有任务与当前状态")
    parser.add_argument("--dry-run", action="store_true", help="只显示将要做的修改")
    args = parser.parse_args(argv)

    path = Path(args.path)
    if not path.exists():
        print(f"找不到排期表：{path}", file=sys.stderr)
        return 2

    wb = load_workbook(path, data_only=False)
    ws = wb["任务明细"]
    rows = collect_rows(ws)

    if args.list:
        print(f"共 {len(rows)} 个任务：")
        for tid, r in rows.items():
            status = ws.cell(row=r, column=STATUS_COL).value
            print(f"  {tid}  M{r:<3} {status}")
        return 0

    if not args.changes:
        parser.print_help()
        return 2

    # 先全部校验，再统一写入——避免改了一半才发现有非法值。
    updates: list[tuple[str, int, str, str]] = []
    errors: list[str] = []
    for item in args.changes:
        if "=" not in item:
            errors.append(f"{item!r} 格式不对，应为 A01=已完成")
            continue
        tid, _, status = item.partition("=")
        tid, status = tid.strip(), status.strip()
        if status not in VALID:
            errors.append(f"{tid}: {status!r} 不是合法状态，允许 {sorted(VALID)}")
            continue
        if tid not in rows:
            errors.append(f"找不到任务 {tid}")
            continue
        r = rows[tid]
        old = ws.cell(row=r, column=STATUS_COL).value
        if old == status:
            print(f"  {tid} (M{r}) 已经是「{status}」，跳过")
            continue
        updates.append((tid, r, str(old), status))

    if errors:
        for e in errors:
            print(f"!! {e}", file=sys.stderr)
        print("有错误，未写入任何改动。", file=sys.stderr)
        return 1

    for tid, r, old, new in updates:
        print(f"  {tid} (M{r}) {old} -> {new}")

    if args.dry_run:
        print(f"[dry-run] 共 {len(updates)} 处改动，未写盘")
        return 0

    # 没有实际改动就不写盘：避免无意义地重写 xlsx（会改变文件时间戳，
    # 也会让 git 把它误判成有修改）。
    if not updates:
        return 0

    for _, r, _, new in updates:
        ws.cell(row=r, column=STATUS_COL).value = new

    wb.save(path)
    print(f"共写入 {len(updates)} 处 -> {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
