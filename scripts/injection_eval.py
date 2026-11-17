"""Score the prompt-injection rules on the built-in corpus, and optionally on YOUR prompts.

    python scripts/injection_eval.py
    python scripts/injection_eval.py --benign my_normal_prompts.txt --attacks my_attacks.txt

Files hold one prompt per line. Run it on a sample of real traffic before trusting the rules:
the built-in corpus is small and written by one author. Reports false positives (ordinary
prompts blocked), misses (attacks not blocked) and ordinary prompts that are only flagged.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.security.content import ContentSecurityEngine  # noqa: E402
from tests import injection_corpus as C  # noqa: E402


def read(path):
    with open(path, encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip()]


def score(engine, name, benign, attacks):
    signal = lambda t: ("BLOCK" if engine.assess(t).blocked else
                        "FLAG" if any(f.category == "PROMPT_INJECTION_SUSPECT" for f in engine.assess(t).findings) else "-")
    fp = [p for p in benign if signal(p) == "BLOCK"]
    flagged = sum(signal(p) == "FLAG" for p in benign)
    caught = [p for p in attacks if signal(p) == "BLOCK"]
    print(f"{name:14s} benign blocked {len(fp):3d}/{len(benign):<3d}  flagged only {flagged:3d}   "
          f"attacks blocked {len(caught):3d}/{len(attacks):<3d}" if attacks else
          f"{name:14s} benign blocked {len(fp):3d}/{len(benign):<3d}  flagged only {flagged:3d}")
    for p in fp: print("    FALSE POSITIVE:", p[:100])
    for p in attacks:
        if p not in caught: print("    MISSED       :", p[:100].replace("\n", "\\n"))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--benign", help="file of ordinary prompts, one per line")
    ap.add_argument("--attacks", help="file of attack prompts, one per line")
    ap.add_argument("--strict", action="store_true", help="also block the flag-only tier (INJECTION_STRICT)")
    args = ap.parse_args()
    engine = ContentSecurityEngine(strict_injection=args.strict)
    score(engine, "dev", C.BENIGN_DEV, C.ATTACKS_DEV)
    score(engine, "holdout", C.BENIGN_HOLDOUT, C.ATTACKS_HOLDOUT)
    score(engine, "holdout2 (fresh)", C.BENIGN_HOLDOUT2, C.ATTACKS_HOLDOUT2)
    if args.benign or args.attacks:
        score(engine, "your prompts", read(args.benign) if args.benign else [], read(args.attacks) if args.attacks else [])


if __name__ == "__main__":
    main()
