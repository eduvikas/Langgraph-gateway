"""Docs hygiene: no broken relative links, no retired filenames, and test counts only in docs/VERIFICATION.md."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = [ROOT / "README.md", ROOT / "CHANGELOG.md", *sorted((ROOT / "docs").glob("*.md"))]
LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")
RETIRED = ("VALIDATION_REPORT", "VERIFICATION_REPORT", "UNIFICATION_CHANGELOG", "MCP_INTEGRATION", "ENTERPRISE_HARDENING", "GUIDE.md")
COUNT = re.compile(r"\b\d+\s+(?:passed|failed|xfailed|tests)\b|\b\d+\s+of\s+\d+\s+checks\b|\b\d+/\d+\s+checks\b", re.I)


def test_docs_exist():
    names = {p.name for p in DOCS}
    assert {"README.md", "CHANGELOG.md", "MCP.md", "VERIFICATION.md", "INTEGRATION.md", "ENGINEERING.md", "HARDENING.md"} <= names


def test_relative_links_resolve():
    broken = []
    for doc in DOCS:
        for target in LINK.findall(doc.read_text(encoding="utf-8")):
            if target.startswith(("http://", "https://", "mailto:", "#")):
                continue
            path = (doc.parent / target.split("#")[0]).resolve()
            if not path.exists():
                broken.append(f"{doc.relative_to(ROOT)} -> {target}")
    assert not broken, broken


def test_retired_documents_are_not_referenced():
    hits = [f"{d.relative_to(ROOT)}: {name}" for d in DOCS for name in RETIRED if name in d.read_text(encoding="utf-8")
            and not (d.name == "CHANGELOG.md" or d.name == "VERIFICATION.md")]
    assert not hits, hits
    for name in ("VALIDATION_REPORT.md", "VERIFICATION_REPORT.md", "GUIDE.md", "INTEGRATION.md", "MCP_INTEGRATION.md"):
        assert not (ROOT / name).exists(), f"{name} should live under docs/ or be removed"


def test_test_counts_are_quoted_only_in_verification_md():
    offenders = {}
    for doc in DOCS:
        if doc.name == "VERIFICATION.md":
            continue
        found = COUNT.findall(doc.read_text(encoding="utf-8"))
        if found:
            offenders[str(doc.relative_to(ROOT))] = found
    assert not offenders, offenders
