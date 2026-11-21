"""查看供项目使用的合成数据，不进行业务分析。"""
import argparse
import json
from pathlib import Path


def read_tables(directory):
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    tables = {}
    for name, columns in manifest.items():
        records = []
        with (directory / f"{name}.jsonl").open(encoding="utf-8") as stream:
            for number, line in enumerate(stream, 1):
                record = json.loads(line)
                if not isinstance(record, dict) or record.keys() != set(columns):
                    raise ValueError(f"{name} 第 {number} 行的字段与登记格式不符")
                records.append(record)
        tables[name] = records
    return tables


def main():
    parser = argparse.ArgumentParser(description="读取合成资料的表和记录数量")
    parser.add_argument("directory", type=Path, nargs="?", default=Path("data"))
    args = parser.parse_args()
    try:
        tables = read_tables(args.directory)
    except (OSError, ValueError) as error:
        parser.exit(2, f"读入失败：{error}\n")
    print(json.dumps({name: len(records) for name, records in tables.items()}, indent=2))


if __name__ == "__main__":
    main()
