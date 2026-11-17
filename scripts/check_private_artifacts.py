"""Reject personal strategy artifacts and credentials from public Git commits.

CI scans every tracked working-tree file; the pre-commit hook scans the
staged Git index, including files force-added despite .gitignore.
"""
from __future__ import annotations
import argparse
import re
import subprocess
import sys
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parent.parent
PRIVATE_ROOTS = {
    "data", ".local-state", "private", ".private", "secrets", ".secrets",
    "exports", "backups", "snapshots", "outputs", "generated", "runs",
    "trading-records", "trade-records", "saved-strategies",
    "strategy-exports", "strategy-results", "optimization-results",
}
PRIVATE_SEGMENTS = {
    "private", ".private", "secrets", ".secrets", "credentials",
    "strategy-exports", "strategy-results", "optimization-results",
    "trade-records", "trading-records", "checkpoints",
}
GENERATED_SUFFIXES = (
    ".sqlite", ".sqlite3", ".db", ".duckdb", ".parquet", ".arrow",
    ".feather", ".csv", ".tsv", ".jsonl", ".ndjson", ".pkl",
    ".pickle", ".joblib", ".onnx", ".pt", ".pth", ".ckpt",
    ".h5", ".hdf5", ".npz", ".npy", ".strategy", ".tradebook",
    ".ipynb", ".bak", ".backup",
)
PRIVATE_EXPORT_NAME = re.compile(
    r"(strategy|strategies|trade|trades|fills|orders|signals|"
    r"positions|holdings|portfolio|broker|account|journal|"
    r"optim(?:ization|isation|ized|ised)|backtest|forecast|"
    r"checkpoint|weights|parameters|model|experiment|performance|pnl)",
    re.IGNORECASE,
)
DATA_EXPORT_SUFFIXES = (".json", ".yaml", ".yml", ".toml", ".xml", ".txt")
PERSONAL_SOURCE_NAME = re.compile(
    r"(?:my|private|personal|generated|trained|best|optimized|"
    r"optimised|deployed|live)[._-].*(?:strategy|model|signal|"
    r"portfolio|trade)|(?:strategy|model|signal|portfolio|trade)"
    r".*[._-](?:private|personal|generated|optimized|optimised|live)",
    re.IGNORECASE,
)
SECRET_PATTERNS = {
    "OpenAI-like API key": re.compile(rb"\bsk-(?:proj-|svcacct-)?[a-zA-Z0-9_-]{25,}\b"),
    "GitHub access token": re.compile(
        rb"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{30,}\b|"
        rb"\bgithub_pat_[A-Za-z0-9_]{20,}\b"
    ),
    "Discord webhook": re.compile(
        rb"https://discord(?:app)?\.com/api/webhooks/\d+/[A-Za-z0-9_-]{15,}"
    ),
    "Slack webhook": re.compile(
        rb"https://hooks\.slack\.com/services/[A-Za-z0-9/_-]{25,}"
    ),
    "private SSH key": re.compile(
        rb"-----BEGIN (?:OPENSSH|RSA|EC|DSA|ENCRYPTED) PRIVATE KEY-----"
    ),
    "AWS access key": re.compile(rb"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
}

def path_violation(name: str) -> str | None:
    normalized = name.replace("\\", "/").lstrip("./")
    parts = tuple(p.lower() for p in PurePosixPath(normalized).parts)
    if not parts or ".." in parts:
        return "unsafe path"
    basename = parts[-1]
    if parts[0] in PRIVATE_ROOTS or any(p in PRIVATE_SEGMENTS for p in parts[:-1]):
        return "private user-data directory"
    if basename == ".env" or basename.startswith(".env."):
        return None if normalized == ".env.example" else "environment credentials"
    if basename.endswith((".pem", ".p12", ".pfx", ".key")):
        return "private key or credentials"
    if any(word in basename for word in ("credential", "secret", "private-key")):
        if basename.endswith((".json", ".yaml", ".yml", ".txt", ".toml", ".ini")):
            return "credential or secret file"
    if basename.endswith(GENERATED_SUFFIXES) or ".sqlite3-" in basename or ".db-" in basename:
        return "generated database, research dataset, model weight, or notebook"
    if basename.endswith(DATA_EXPORT_SUFFIXES) and PRIVATE_EXPORT_NAME.search(basename):
        return "strategy/trading export: use private storage"
    if basename.endswith((".py", ".ts", ".tsx", ".js", ".mjs")) and PERSONAL_SOURCE_NAME.search(basename):
        return "personal or generated strategy source"
    return None

def content_violation(filename: str, data: bytes) -> str | None:
    if len(data) > 3_000_000:
        return "oversized tracked content: audit before publishing"
    if b"\x00" in data:
        return None
    for kind, pattern in SECRET_PATTERNS.items():
        if pattern.search(data):
            return kind
    suffix = PurePosixPath(filename).suffix.lower()
    if suffix in (".json", ".yaml", ".yml", ".toml", ".xml", ".txt"):
        if re.search(
            rb'(?i)"(?:strategy|strategy_code|rules|dsl|signal_logic)"\s*:\s*"WHEN\s+[^"]{10,}',
            data,
        ):
            return "serialized private trading rules"
    return None

def git(*args: str) -> bytes:
    proc = subprocess.run(["git", *args], cwd=ROOT, capture_output=True)
    if proc.returncode:
        raise RuntimeError(proc.stderr.decode("utf-8", errors="replace"))
    return proc.stdout

def candidates(staged: bool):
    for raw in git("ls-files", "--cached", "-z").split(b"\0"):
        if not raw:
            continue
        filename = raw.decode("utf-8", errors="surrogateescape")
        if staged:
            blob = subprocess.run(
                ["git", "show", ":" + filename], cwd=ROOT, capture_output=True,
            )
            if blob.returncode:
                continue
            yield filename, blob.stdout
        else:
            path = ROOT / filename
            if path.is_file():
                yield filename, path.read_bytes()

def run(staged: bool = False) -> int:
    issues = []
    for filename, data in candidates(staged):
        problem = path_violation(filename) or content_violation(filename, data)
        if problem:
            issues.append((filename, problem))
    if issues:
        print("PRIVATE TRADING DATA CHECK FAILED. Do not commit or push:", file=sys.stderr)
        for filename, problem in issues:
            # Deliberately never print strategy code or credential values.
            print("  " + filename + ": " + problem, file=sys.stderr)
        print(
            "Move private material into data/, .local-state/, private/, or storage "
            "outside the Git repository. Do not force-add it. Removing already "
            "pushed content from a later commit does not remove it from Git history.",
            file=sys.stderr,
        )
        return 1
    print("Privacy check passed: no tracked private artifacts or detected credentials.")
    return 0

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--staged", action="store_true", help="scan Git index including force-added files")
    args = parser.parse_args()
    try:
        return run(staged=args.staged)
    except (OSError, RuntimeError) as exc:
        print("Privacy check unavailable: refusing to approve commit. " + str(exc), file=sys.stderr)
        return 2

if __name__ == "__main__":
    sys.exit(main())
