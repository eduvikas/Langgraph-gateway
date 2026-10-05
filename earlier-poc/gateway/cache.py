"""Response cache: exact match plus a 'semantic' match.

The semantic match here is token-set similarity so the PoC has zero dependencies.
In production swap norm_tokens/jaccard for embeddings + a vector store (same interface).
Cache entries are scoped per application so one team never sees another team's answers.
"""
import hashlib
import re
from collections import Counter, defaultdict

from .config import CACHE_TTL_S, SEMANTIC_THRESHOLD

STOP = set("""a an the to of and or for in on at is are was were be do does did i me my you your we our it
this that with can could would will please hi hello hey thanks thank kindly quick question tell what how
when where which who get""".split())


def norm_tokens(text):
    return frozenset(w for w in re.findall(r"[a-z0-9_]+", text.lower()) if w not in STOP)


def jaccard(a, b):
    return len(a & b) / len(a | b) if a and b else 0.0


class ResponseCache:
    def __init__(self):
        self.exact = {}
        self.entries = []                    # (app, tokens, entry)
        self.index = defaultdict(set)        # (app, token) -> entry ids
        self.stats = Counter()

    @staticmethod
    def _key(app, prompt):
        return (app, hashlib.md5(prompt.strip().lower().encode()).hexdigest())

    def get(self, app, prompt, ts):
        entry = self.exact.get(self._key(app, prompt))
        if entry and ts - entry["ts"] <= CACHE_TTL_S:
            self.stats["exact"] += 1
            return "exact", entry
        toks = norm_tokens(prompt)
        if toks:
            rare = sorted(toks, key=lambda t: len(self.index.get((app, t), ())))[:3]
            cands = set()
            for t in rare:
                cands |= self.index.get((app, t), set())
            best, best_sim = None, 0.0
            for i in cands:
                _, etoks, e = self.entries[i]
                if ts - e["ts"] > CACHE_TTL_S:
                    continue
                sim = jaccard(toks, etoks)
                if sim > best_sim:
                    best, best_sim = e, sim
            if best is not None and best_sim >= SEMANTIC_THRESHOLD:
                self.stats["semantic"] += 1
                return "semantic", best
        self.stats["miss"] += 1
        return None

    def put(self, app, prompt, ts, entry):
        entry = dict(entry, ts=ts)
        self.exact[self._key(app, prompt)] = entry
        toks = norm_tokens(prompt)
        idx = len(self.entries)
        self.entries.append((app, toks, entry))
        for t in toks:
            self.index[(app, t)].add(idx)
