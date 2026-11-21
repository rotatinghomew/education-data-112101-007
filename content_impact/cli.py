"""命令行入口：python3 -m content_impact [--data-dir data] [--asset A-1] [--json]"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .model import Dataset
from .report import json_default, render_text, to_dict
from .scope import analyze, filter_by_asset


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="content_impact",
        description="从内容证据到传播影响范围的分析：圈定处置范围、检查措施覆盖、安排复核。",
    )
    parser.add_argument("--data-dir", default="data", help="资料目录（默认 data/）")
    parser.add_argument("--asset", help="只查看指定素材相关的家族、缺口与措施记录")
    parser.add_argument("--json", action="store_true", help="输出 JSON 而非文本报告")
    args = parser.parse_args(argv)

    dataset = Dataset.load(Path(args.data_dir))
    result = analyze(dataset)
    if args.asset:
        result = filter_by_asset(result, dataset, args.asset)

    if args.json:
        print(json.dumps(to_dict(result), ensure_ascii=False, indent=2, default=json_default))
    else:
        print(render_text(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
