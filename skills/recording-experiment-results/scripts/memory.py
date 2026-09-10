#!/usr/bin/env python3
"""Register, finish and check experiment records using the standard library."""
import argparse
import csv
import os
import tempfile
from pathlib import Path
import re
import sys
from urllib.parse import unquote, urlsplit

COLUMNS = ["task", "简介", "指标", "结论", "输出目录"]


def check_csv(path, root, outputs, report, *, check_outputs=True):
    """Report CSV shape, state and output-reference problems without editing it.

    变更: 2026-09-08 写入时可跳过输出可用性检查；exp-check 仍报告缺失产物。
    """
    count = 0
    seen = set()
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream, strict=True)
        if reader.fieldnames != COLUMNS:
            report("ERROR", path, "expected columns: " + ",".join(COLUMNS))
            return count
        for row in reader:
            location = f"{path}:{reader.line_num}"
            count += 1
            if None in row or any(value is None for value in row.values()):
                report("ERROR", location, "malformed CSV row")
                continue
            task = row["task"]
            if not task.strip() or task in {".", ".."} or "/" in task or "\\" in task:
                report("ERROR", location, "invalid task")
            if task in seen:
                report("ERROR", location, f"duplicate task: {task}")
            seen.add(task)
            output = row["输出目录"]
            if task == "summary":
                # Summary may reference the winner, an analysis directory, or no baseline.
                if check_outputs and output.strip() not in {"", "—"} and not (root / output).is_dir():
                    report("ERROR", location, f"summary output missing: {output}")
                continue
            if not row["简介"].strip():
                report("ERROR", location, "missing experiment plan")
            if output.strip() in {"", "—"}:
                report("ERROR", location, "missing output path")
                continue
            destination = (root / output).resolve()
            if Path(output).name != task:
                report("ERROR", location, "output leaf does not match task")
            if destination in outputs:
                report("WARN", location, f"output also referenced by {outputs[destination]}")
            else:
                outputs[destination] = location
            conclusion = row["结论"].strip()
            if conclusion:
                if not re.match(r"^(keep|discard|crash|timeout)(?:\s|:|：)", conclusion):
                    report("ERROR", location, "invalid conclusion status")
                if not row["指标"].strip():
                    report("ERROR", location, "missing metrics; use — when unavailable")
                if check_outputs and not destination.is_dir():
                    report("ERROR", location, f"finished output missing: {output}")
            elif check_outputs and destination.exists() and not destination.is_dir():
                report("ERROR", location, f"output is not a directory: {output}")
    return count


def check_links(path, report):
    """Check supported inline local links outside Markdown code."""
    # Deliberately limited to inline Markdown links; fenced code is not evidence.
    fence = None
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        marker = re.match(r"^\s{0,3}(`{3,}|~{3,})", line)
        if marker:
            token = marker[1]
            if fence is None:
                fence = token
            elif token[0] == fence[0] and len(token) >= len(fence):
                fence = None
            continue
        if fence:
            continue
        line = re.sub(r"(`+).*?\1", "", line)
        for match in re.finditer(r"\[[^\]\n]*\]\(\s*(?:<([^>]+)>|([^\s)]+))(?:\s+\"[^\"]*\")?\s*\)", line):
            target = match[1] or match[2]
            parts = urlsplit(target)
            if parts.scheme or parts.netloc or not parts.path:
                continue
            destination = path.parent / unquote(parts.path)
            if not destination.exists():
                report("ERROR", f"{path}:{number}", f"broken local link: {target}")


def check_experiments(args):
    """Scan only the requested scope and return bounded diagnostics."""
    counts = {"ERROR": 0, "WARN": 0}

    def report(level, location, message):
        """Count every finding but print only the requested number."""
        counts[level] += 1
        if sum(counts.values()) <= max(0, args.limit):
            print(f"{level} {location}: {message}")

    try:
        root = args.root.resolve()
        records = (root / args.records).resolve()
        scope = (records / args.scope).resolve() if args.scope else records
        if not records.is_dir() or not records.is_relative_to(root):
            raise ValueError("records must be an existing directory inside root")
        if not scope.exists() or not scope.is_relative_to(records):
            raise ValueError("scope must exist inside records")
        files = sorted(scope.rglob("*")) if scope.is_dir() else [scope]
        files = [p for p in files if p.is_file() and p.suffix.lower() in {".csv", ".md"}]
        if not files:
            raise ValueError("no CSV or Markdown files in scope")
        outputs = {}
        rows = csv_count = md_count = 0
        for path in files:
            try:
                if path.suffix.lower() == ".csv":
                    csv_count += 1
                    rows += check_csv(path, root, outputs, report)
                else:
                    md_count += 1
                    check_links(path, report)
            except (OSError, ValueError, csv.Error) as error:
                report("ERROR", path, str(error))
        print(f"Checked scope={scope}; CSV={csv_count}, rows={rows}, Markdown={md_count}; "
              f"errors={counts['ERROR']}, warnings={counts['WARN']}")
        omitted = sum(counts.values()) - max(0, args.limit)
        if omitted > 0:
            print(f"{omitted} diagnostics omitted; increase --limit for details")
        return 1 if counts["ERROR"] else 0
    except (OSError, ValueError) as error:
        print(f"ERROR: {error}")
        return 1


def write_experiment(args):
    """Append a plan or finish one pending row; validate before replacing the CSV.

    变更: 2026-09-08 输出存在或缺失不再阻止登记；格式与覆盖保护保留。
    """
    root = args.root.resolve()
    records = (root / args.records).resolve()
    path = (records / args.csv).resolve()
    if not records.is_relative_to(root) or not path.is_relative_to(records) or path.suffix != ".csv":
        raise ValueError("CSV must be inside records and end in .csv")
    if args.task == "summary":
        raise ValueError("summary is a group conclusion, not an experiment attempt")
    planning = args.operation == "plan"
    if not planning and not path.is_file():
        raise ValueError("experiment CSV not found")
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = path.with_name(path.name + ".lock")
    # Exclusive lock protects read-modify-write among these CLI writers; never steal a stale lock.
    with lock.open("x"):
        pass
    temporary = None
    try:
        original = path.read_bytes() if path.exists() else None
        rows = []
        if original is not None:
            with path.open(encoding="utf-8-sig", newline="") as stream:
                reader = csv.DictReader(stream, strict=True)
                if reader.fieldnames != COLUMNS:
                    raise ValueError("expected standard five-column experiment CSV")
                rows = list(reader)
                if any(None in row or any(value is None for value in row.values()) for row in rows):
                    raise ValueError("malformed existing CSV row")
        matches = [row for row in rows if row["task"] == args.task]
        if planning:
            if matches:
                raise ValueError("task already registered; inspect it before resuming")
            rows.append(dict(zip(COLUMNS, [args.task, args.purpose, "", "", args.output])))
        else:
            if len(matches) != 1:
                raise ValueError("expected exactly one registered task")
            if matches[0]["结论"].strip():
                raise ValueError("result already recorded; review corrections explicitly")
            if not args.conclusion.strip():
                raise ValueError("conclusion reason is required")
            matches[0].update({"指标": args.metrics, "结论": args.status + "：" + args.conclusion})
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="", dir=path.parent,
                                         prefix="." + path.name, suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            writer = csv.DictWriter(stream, fieldnames=COLUMNS)
            writer.writeheader()
            writer.writerows(rows)
            stream.flush()
            os.fsync(stream.fileno())
        errors = []
        def report(level, location, message):
            """Reject invalid candidate records before touching the original CSV."""
            if level == "ERROR":
                errors.append(message)
            else:
                print(f"WARN: {message}")
        check_csv(temporary, root, {}, report, check_outputs=False)
        if errors:
            raise ValueError("; ".join(errors[:5]))
        if (path.read_bytes() if path.exists() else None) != original:
            raise ValueError("CSV changed outside this command; retry after inspection")
        if original is not None:
            os.chmod(temporary, path.stat().st_mode)
        os.replace(temporary, path)
        print(f"Recorded {args.task}: {path}")
        return 0
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        lock.unlink()


# Public names live here; rename a key without changing the operation or implementation.
COMMANDS = {
    "exp-plan": (write_experiment, "plan"),
    "exp-finish": (write_experiment, "finish"),
    "exp-check": (check_experiments, "check"),
}


def main():
    """Parse experiment-specific commands; report failures without modifying old records.

    变更: 2026-09-08 check renamed exp-check; added explicit plan and finish writes.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name, (handler, operation) in COMMANDS.items():
        command = commands.add_parser(name)
        command.set_defaults(handler=handler, operation=operation)
        command.add_argument("--root", type=Path, required=True, help="project root and CSV output-path base")
        command.add_argument("--records", type=Path, required=True, help="records directory relative to root")
        if operation == "check":
            command.add_argument("--scope", type=Path, help="file/subdirectory relative to records")
            command.add_argument("--limit", type=int, default=20, help="maximum diagnostic lines")
        else:
            command.add_argument("--csv", type=Path, required=True, help="CSV path relative to records")
            command.add_argument("--task", required=True)
            if operation == "plan":
                command.add_argument("--purpose", required=True, help="why this experiment is needed")
                command.add_argument("--output", required=True, help="actual output path relative to root")
            else:
                command.add_argument("--metrics", required=True)
                command.add_argument("--status", required=True, choices=["keep", "discard", "crash", "timeout"])
                command.add_argument("--conclusion", required=True, help="reason and next step")
    args = parser.parse_args()
    try:
        return args.handler(args)
    except (OSError, ValueError, csv.Error, KeyError, TypeError) as error:
        print(f"ERROR: {error}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
