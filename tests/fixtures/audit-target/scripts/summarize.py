from pathlib import Path
import sys


def first_lines(path, count=5):
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    return "\n".join(lines[:count - 1])


if __name__ == "__main__":
    print(first_lines(sys.argv[1]))
