"""Print deterministic fillable-PDF extraction as JSON, without calling an LLM."""

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.parser import extract_fields


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract fillable PDF questions as JSON.")
    parser.add_argument("pdf", type=Path)
    args = parser.parse_args()
    fields = extract_fields(args.pdf.read_bytes())
    print(json.dumps([field.model_dump() for field in fields], indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
