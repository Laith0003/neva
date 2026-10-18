"""Accept only successful, nonempty test-runner summaries."""
import re
import sys


def accepts(kind, status, output):
    if status != 0:
        return False
    if kind == "python":
        counts = re.findall(r"^Ran ([0-9]+) tests? in .+$", output, re.M)
        outcomes = re.findall(r"^(OK(?: \(skipped=[0-9]+\))?|FAILED.*)$", output, re.M)
        if len(counts) != 1 or len(outcomes) != 1 or not outcomes[0].startswith("OK"):
            return False
        skipped = re.search(r"skipped=([0-9]+)", outcomes[0])
        return int(counts[0]) > (int(skipped.group(1)) if skipped else 0)
    if kind == "node":
        pairs = re.findall(r"^(?:#|ℹ) (tests|pass|fail|cancelled|skipped|todo) ([0-9]+)$", output, re.M)
        values = dict(pairs)
        if len(pairs) != len(values) or not {"tests", "pass", "fail", "cancelled"}.issubset(values):
            return False
        return (int(values.get("tests", "0")) > 0 and int(values.get("pass", "0")) > 0
                and values["fail"] == "0" and values["cancelled"] == "0"
                and int(values["tests"]) == sum(int(values.get(key, "0")) for key in ("pass", "fail", "cancelled", "skipped", "todo")))
    return False


if __name__ == "__main__":
    try:
        accepted = accepts(sys.argv[1], int(sys.argv[2]), sys.stdin.read())
    except (IndexError, ValueError):
        accepted = False
    print("suite accepted" if accepted else "suite refused: require successful exit and nonempty passing execution",
          file=sys.stdout if accepted else sys.stderr)
    sys.exit(0 if accepted else 1)
