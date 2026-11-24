"""Find tested SOP examples or extract an editable scene without overwriting a file."""
import argparse
import errno
import gzip
import hashlib
import json
import os
import tempfile
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("query", help="example ID, title, wiring or measured effect")
    parser.add_argument("--export", type=Path, help="write one exact ID to a new HIP file")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    records = json.loads((root / "references/示例索引.json").read_text(encoding="utf-8"))

    if args.export is None:
        term = args.query.casefold()
        matches = [r for r in records if any(term in r[k].casefold()
                   for k in ("id", "title", "wiring", "observation"))]
        if not matches:
            parser.exit(1, "没有匹配的实测小样。\n")
        for row in matches:
            print(f"{row['id']}  {row['title']}\n  {row['wiring']}\n  {row['observation']}")
        return

    row = next((r for r in records if r["id"] == args.query), None)
    if row is None:
        parser.error("导出需要完整小样 ID。")
    scene = Path(row["file"]).stem
    if args.export.suffix.lower() != Path(scene).suffix:
        parser.error(f"请保留该工程的 {Path(scene).suffix} 扩展名。")
    source = root / "assets/examples" / row["file"]
    data = gzip.decompress(source.read_bytes())
    if hashlib.sha256(data).hexdigest() != row["sha256"]:
        parser.exit(1, "示例摘要核对失败。\n")

    try:
        with tempfile.NamedTemporaryFile(dir=args.export.parent) as tmp:
            tmp.write(data)
            tmp.flush()
            try:
                os.link(tmp.name, args.export)
            except OSError as exc:
                # Some removable volumes do not support hard links.
                if exc.errno not in {errno.EPERM, errno.ENOSYS, errno.ENOTSUP, errno.EOPNOTSUPP}:
                    raise
                with args.export.open("xb") as out:
                    try:
                        out.write(data)
                        out.flush()
                    except BaseException:
                        args.export.unlink(missing_ok=True)
                        raise
    except FileExistsError:
        parser.exit(1, "输出已存在，请使用新文件名。\n")
    except OSError as exc:
        parser.exit(1, f"写入失败：{exc}\n")
    print(args.export.resolve())


if __name__ == "__main__":
    main()
