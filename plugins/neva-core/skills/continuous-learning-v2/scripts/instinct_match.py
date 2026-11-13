"""instinct_match: lexical relevance between a query and instinct notes. Standard library only.

Pure functions, no I/O, no model call, no network. The hooks load this file by path (it ships
with the skill), and the CLI imports it, so the interface below is the contract. A local
embedding scorer can replace the lexical one later without touching the callers.

  tokens(text)                 ordered, de-duplicated stems of `text`, stop words removed
  query_tokens(text)           the same, bounded: a frozenset of at most MAX_QUERY_STEMS stems
                               taken from the first MAX_QUERY_CHARS characters
  item_tokens(item)            stems of an instinct's trigger, id and tags (what a query matches)
  Idf(token_sets)              document frequency over the whole instinct corpus (every active
                               note in every project and global, not only the candidates)
  Idf.from_counts(df, n)       the same from cached counts
  score(query, item, idf)      Match(score, shared, qualifies); pass a prepared query set when
                               scoring many items, so the query is built once
  near_duplicate(a, b)         Jaccard on action plus trigger stems, at or above 0.6
  rank(query, items, ...)      qualifying items, best first, near-duplicates collapsed

A match qualifies on MIN_SHARED shared stems, or on one rare stem: found in RARE_DF or fewer
instincts corpus-wide AND in at most RARE_SHARE of them. A small corpus therefore has no rare
stems, and only two stem matches count. Lexical and English only: text in another script yields no tokens.
"""
import math
import re
from collections import namedtuple

MIN_SHARED = 2
# A pasted file is not a query. Both bounds keep one prompt from costing more than the hook's
# budget: the text is tokenized up to the first MAX_QUERY_CHARS, and only the first
# MAX_QUERY_STEMS distinct stems are kept, so scoring one note is bounded whatever arrives.
MAX_QUERY_CHARS = 8000
MAX_QUERY_STEMS = 200
RARE_DF = 3
RARE_SHARE = 0.02
DUPLICATE_JACCARD = 0.6

_WORD = re.compile(r"[a-z0-9]+")

# Function words, plus words every instinct trigger uses ("when ... needs to ..."), so they never
# count as a match.
STOP_WORDS = frozenset("""
a about above after again against all also am an and any are as at be been before being below
between both but by can could did do does doing done during each either else etc ever every for
from further get gets got had has have having here how i if in into is it its itself just let lets
like may me might more most must my no nor not now of off on once only or other our out over own
per please same should so some such than that the their them then there these they this those
through to too under until up upon us use used uses using very via was we were what when whenever
where whether which while who whom why will with within without would yes yet you your
need needs needed want wants wanted make makes made run runs one two first new way thing things
""".split())


def stem(word):
    """A deliberately small suffix stripper: plural and common verb endings only. Enough to make
    test/tests/testing and board/boards meet; never so eager that unrelated words collide."""
    w = word
    if len(w) > 4 and w.endswith("ies"):
        return w[:-3] + "y"
    if len(w) > 5 and w.endswith("ing"):
        w = w[:-3]
        return w[:-1] if len(w) > 3 and w[-1] == w[-2] else w
    if len(w) > 4 and w.endswith("ed") and not w.endswith("eed"):
        w = w[:-2]
        return w[:-1] if len(w) > 3 and w[-1] == w[-2] else w
    if len(w) > 3 and w.endswith("s") and not w.endswith(("ss", "us", "is")):
        w = w[:-1]
    if len(w) > 4 and w.endswith("e"):
        w = w[:-1]
    return w


def tokens(text, stop=STOP_WORDS):
    """Ordered unique stems of `text`. Lowercase ASCII words of 2 or more characters; pure numbers
    and stop words dropped. `stop` lets a caller add its own noise words (path parts, say)."""
    out, seen = [], set()
    for w in _WORD.findall(str(text or "").lower()):
        if len(w) < 2 or w.isdigit() or w in stop:
            continue
        s = stem(w)
        if s in stop or s in seen:
            continue
        seen.add(s)
        out.append(s)
    return out


def query_tokens(text):
    """A bounded, prepared query: frozenset of at most MAX_QUERY_STEMS stems from the first
    MAX_QUERY_CHARS characters. Already-tokenized input is truncated, not re-tokenized."""
    if isinstance(text, (set, frozenset)):
        toks = list(text)
    elif isinstance(text, str):
        toks = tokens(text[:MAX_QUERY_CHARS])
    else:
        toks = list(text or ())
    return frozenset(toks[:MAX_QUERY_STEMS])


def _field(item, key):
    v = item.get(key) if isinstance(item, dict) else None
    if isinstance(v, (list, tuple)):
        return " ".join(str(x) for x in v)
    return str(v or "")


def item_tokens(item):
    """What a query is matched against: the trigger, the id (a slug of the lesson) and the tags.
    The action is left out: it is long and generic, and would match nearly every query."""
    if not isinstance(item, dict):
        return set(item or ())
    tags = [t for t in tokens(_field(item, "tags")) if t != "instinct"]
    return set(tokens(_field(item, "trigger"))) | set(tokens(_field(item, "id"))) | set(tags)


class Idf:
    """Document frequency over the corpus token sets."""

    def __init__(self, token_sets=()):
        self.n = 0
        self.df = {}
        for ts in token_sets:
            self.n += 1
            for t in set(ts):
                self.df[t] = self.df.get(t, 0) + 1

    @classmethod
    def from_counts(cls, df, n):
        idf = cls()
        idf.df = {str(k): int(v) for k, v in dict(df).items()}
        idf.n = int(n)
        return idf

    def count(self, stem_):
        return self.df.get(stem_, 0)

    def weight(self, stem_):
        return math.log(1.0 + (self.n + 1.0) / (self.count(stem_) + 1.0))

    def rare(self, stem_):
        k = self.count(stem_)
        return 0 < k <= RARE_DF and k <= RARE_SHARE * self.n


Match = namedtuple("Match", "score shared qualifies")


def score(query, item, idf):
    """Match of `query` (text, stems, or a frozenset from query_tokens) against `item` (an
    instinct dict or a set of stems). Set intersection, so the cost follows the smaller side."""
    q = query if isinstance(query, frozenset) else query_tokens(query)
    have = item_tokens(item)
    shared = tuple(sorted(q & have))
    if not shared:
        return Match(0, (), False)
    total = round(sum(idf.weight(t) for t in shared), 6)
    ok = len(shared) >= MIN_SHARED or any(idf.rare(t) for t in shared)
    return Match(total, shared, ok)


def _dup_tokens(item):
    if not isinstance(item, dict):
        return set(item or ())
    return set(tokens(_field(item, "action") + " " + _field(item, "trigger")))


def jaccard(a, b):
    if not a and not b:
        return 0.0
    return len(a & b) / float(len(a | b))


def near_duplicate(a, b, threshold=DUPLICATE_JACCARD):
    """True when two instincts say nearly the same thing: Jaccard on action plus trigger stems."""
    return jaccard(_dup_tokens(a), _dup_tokens(b)) >= threshold


def _num(v, default=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _date_key(v):
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", str(v or ""))
    return int(m.group(1) + m.group(2) + m.group(3)) if m else 0


def order_key(item, match_score=0.0):
    """Match score, project before global, last_observed, evidence_count, confidence. Never id.
    Items equal on all five keep their input order (Python's sort is stable)."""
    return (-_num(match_score), 0 if item.get("_scope") == "project" else 1,
            -_date_key(item.get("last_observed") or item.get("date")),
            -_num(item.get("evidence_count")), -_num(item.get("confidence")))


def collapse(ordered, seen=(), limit=None):
    """Keep the first of each near-duplicate group from an already ordered list, stopping once
    `limit` entries are kept. Anything that near-duplicates an item in `seen` (already shown) is
    dropped as well. Each note is tokenized once, and each candidate is compared only with what
    is kept so far plus `seen`, so the cost is O(n * (limit + len(seen))), not O(n^2)."""
    kept = []
    prior = [_dup_tokens(k) for k in seen]
    for entry in ordered:
        if limit is not None and len(kept) >= limit:
            break
        it = entry[0] if isinstance(entry, tuple) else entry
        toks = _dup_tokens(it)
        if any(jaccard(toks, k) >= DUPLICATE_JACCARD for k in prior):
            continue
        kept.append(entry)
        prior.append(toks)
    return kept


def rank(query, items, limit, idf=None, seen=()):
    """Qualifying items for `query`, best first, near-duplicates collapsed: [(item, Match)]."""
    if limit <= 0:
        return []
    idf = idf or Idf(item_tokens(i) for i in items)
    q = query_tokens(query)
    scored = [(i, score(q, i, idf)) for i in items]
    scored = [(i, m) for i, m in scored if m.qualifies]
    scored.sort(key=lambda e: order_key(e[0], e[1].score))
    return collapse(scored, seen, limit)
