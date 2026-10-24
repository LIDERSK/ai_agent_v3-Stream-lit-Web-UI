"""Prehľad CSV: python profile_csv.py subor.csv  (len štandardná knižnica)."""
import csv
import sys
from collections import Counter

MAX_ROWS = 100_000


def num(v):
    try:
        return float(str(v).replace(",", ".").strip())
    except ValueError:
        return None


def main(path):
    with open(path, newline="", encoding="utf-8-sig") as f:
        sample = f.read(4096)
        f.seek(0)
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        except csv.Error:
            dialect = csv.excel
        rows = []
        reader = csv.reader(f, dialect)
        header = next(reader, [])
        for i, r in enumerate(reader):
            if i >= MAX_ROWS:
                print(f"(načítaných prvých {MAX_ROWS} riadkov)")
                break
            rows.append(r)
    print(f"Riadkov: {len(rows)}, stĺpcov: {len(header)}")
    for j, name in enumerate(header):
        col = [r[j].strip() if j < len(r) else "" for r in rows]
        empty = sum(1 for v in col if v == "")
        nums = [n for n in (num(v) for v in col if v != "") if n is not None]
        line = f"- {name}: prázdnych {empty}"
        if col and len(nums) >= 0.8 * (len(col) - empty) and nums:
            line += f", číselný: min {min(nums):g}, max {max(nums):g}, priemer {sum(nums) / len(nums):.4g}"
        else:
            top = Counter(v for v in col if v).most_common(3)
            line += f", text: unikátnych {len(set(col))}, najčastejšie " + "; ".join(f"{v[:20]}×{c}" for v, c in top)
        print(line)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("Použitie: profile_csv.py subor.csv")
    main(sys.argv[1])
