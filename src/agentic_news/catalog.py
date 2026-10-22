"""Catalog: dynamic dimensions, rules that select cells, and batching of cells into agent jobs.

Local: a *dimension* (topic, interval, type, ... or any user-added one) is a list of options; a *cell* is one
option id per dimension (the most granular unit, with its own results); a *rule* is a table row selecting the
Cartesian product of chosen ids per dimension; `build_jobs` groups the selected cells into agents by the
dimensions the user did NOT merge. Pure data and functions, no I/O.
Global context: RunConfig (config.py) stores dimensions + rules; the pipeline turns them into cells and jobs, and
each job becomes one Codex agent whose prompt/schema are generated from the same dimensions.
"""

import re  # slugify labels into ids and folder names
from dataclasses import dataclass, replace  # immutable records + modified copies
from datetime import date, timedelta  # interval date arithmetic
from itertools import groupby, product  # group cells per agent; Cartesian product of rule values
from math import prod  # size of a full product

Cell = tuple[str, ...]  # one option id per dimension, in dimension order
RESERVED_KEYS = {"title", "url", "published", "creator", "summary", "why_notable", "in_interval", "url_seen",
                 "run_id", "agent", "run", "coverage_notes", "items"}  # result/rule/schema fields


@dataclass(frozen=True)
class Option:
    """One entry of a dimension."""

    id: str  # stable machine id used in prompts, schema enums and results
    label: str  # human label shown in the dashboard
    definition: str = ""  # meaning, copied into the agent prompt
    days: int | None = None  # interval options only: how many days back from today


@dataclass(frozen=True)
class Dimension:
    """One axis of the cell space (topic, interval, ... or user-defined)."""

    key: str  # stable id; also the field name in the output schema and results
    label: str  # human label
    description: str = ""  # explains the dimension to the agent
    kind: str = "category"  # "category" or "interval" (options carry days -> date ranges and checks)
    options: tuple[Option, ...] = ()

    def option(self, oid: str) -> Option:
        """Option by id (KeyError if unknown)."""
        for opt in self.options:
            if opt.id == oid:
                return opt
        raise KeyError(f"{self.key}: unknown option {oid!r}")

    @property
    def ids(self) -> list[str]:
        """Option ids in display order."""
        return [o.id for o in self.options]


DEFAULT_TOPICS = [  # the user's 24 topics, in the order they were requested
    "AI industry", "AI research", "Mechanistic interpretability", "Physics", "Fundamental physics",
    "Pure math", "Applied math", "AI in math", "AI in physics", "AI for AI research",
    "AI for software engineering", "RSI", "LLMs", "Agents", "Reinforcement learning",
    "Philosophy of science", "AI governance", "Memetic tribes in AI", "Software engineering",
    "Consciousness", "Neuroscience", "General natural science", "General science", "Philosophy",
]


def slugify(text: str) -> str:
    """Lowercase, non-alphanumerics collapsed to '-' (safe ids and folder names on Windows and POSIX)."""
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def default_dimensions() -> list[Dimension]:
    """The built-in five dimensions; users can edit, remove or add to them."""
    return [
        Dimension("topic", "Topic", "the subject area to cover", "category",
                  tuple(Option(slugify(t), t) for t in DEFAULT_TOPICS)),
        Dimension("interval", "Interval", "publication date range, counted back from today", "interval", (
            Option("day", "Last day", "published in the last 24 hours", 1),
            Option("week", "Last week", "published in the last 7 days", 7),
            Option("month", "Last month", "published in the last 30 days", 30),
            Option("year", "Last year", "published in the last 365 days", 365),
            Option("decade", "Last 10 years", "landmark, most influential works of the last 10 years", 3652),
            Option("century", "Last 100 years", "landmark, most influential works of the last 100 years", 36524))),
        Dimension("type", "Type", "the form of the item", "category", (
            Option("paper", "Papers", "research paper or preprint (arXiv, journal, conference, technical report)"),
            Option("article", "Articles", "news article, blog post, essay or newsletter issue"),
            Option("book", "Books", "book (popular or academic, including textbooks)"),
            Option("video", "Videos", "video (YouTube, recorded talk or lecture, documentary)"),
            Option("podcast", "Podcasts", "podcast episode"))),
        Dimension("source", "Source", "how the item became notable", "category", (
            Option("viral_papers", "Viral papers", "papers that drew unusual attention (trending on Hugging Face "
                   "Papers or alphaXiv, high citation velocity, widely discussed by researchers)"),
            Option("viral_news", "Viral news", "stories covered widely by news outlets or high on Hacker News/Reddit"),
            Option("viral_tweets", "Viral tweets", "content that spread on X/Twitter (or Bluesky/Threads) with high "
                   "engagement; the item may be the post itself or what it linked to"),
            Option("viral_content", "Viral internet content", "anything else that spread widely online "
                   "(blog posts, YouTube videos, Substack essays, forum threads)"))),
        Dimension("variant", "Variant", "the audience level", "category", (
            Option("pop_sci", "Pop sci", "accessible to a general audience (journalism, explainers, popular books)"),
            Option("rigorous", "Rigorous", "primary or technical source for experts (papers, technical reports, "
                   "textbooks, lectures, expert talks)"))),
    ]


def validate_dimensions(dims: list[Dimension]) -> list[str]:
    """Human-readable problems; an empty list means the dimensions are usable."""
    errors = [] if dims else ["at least one dimension is required"]
    keys = [d.key for d in dims]
    for d in dims:
        if not d.key or d.key != slugify(d.key).replace("-", "_"):
            errors.append(f"dimension key {d.key!r} must be lowercase letters, digits or _")
        if d.key in RESERVED_KEYS:
            errors.append(f"dimension key {d.key!r} is reserved")
        if keys.count(d.key) > 1:
            errors.append(f"duplicate dimension key {d.key!r}")
        if not d.options:
            errors.append(f"dimension {d.key!r} has no entries")
        if len(set(d.ids)) != len(d.ids) or not all(d.ids):
            errors.append(f"dimension {d.key!r} has empty or duplicate entry ids")
        if d.kind == "interval" and not all(isinstance(o.days, int) and o.days > 0 for o in d.options):
            errors.append(f"interval dimension {d.key!r} needs a positive number of days for every entry")
    if sum(d.kind == "interval" for d in dims) > 1:
        errors.append("at most one interval dimension is allowed")
    return list(dict.fromkeys(errors))  # dedupe, keep order


def default_rules(dims: list[Dimension]) -> list[dict]:
    """One unchecked rule per entry of the first dimension, every other dimension fully selected."""
    first, *rest = dims
    return [{"run": False, first.key: [o.id], **{d.key: d.ids for d in rest}} for o in first.options]


def sync_rules(rules: list[dict], dims: list[Dimension]) -> list[dict]:
    """Fit rules to edited dimensions: drop unknown ids/dims, fully select new dims, add rules for new first entries."""
    synced = [{"run": bool(r.get("run")),
               **{d.key: [i for i in d.ids if i in set(r[d.key])] if d.key in r else d.ids for d in dims}}
              for r in rules]
    if not dims:
        return synced
    covered = {i for r in synced for i in r[dims[0].key]}
    new_first = tuple(o for o in dims[0].options if o.id not in covered)  # entries no rule mentions yet
    return synced + default_rules([replace(dims[0], options=new_first), *dims[1:]])


def _sort_key(dims: list[Dimension]):
    """Cell -> tuple of option positions (canonical, display order)."""
    pos = [{oid: n for n, oid in enumerate(d.ids)} for d in dims]
    return lambda cell: tuple(p[v] for p, v in zip(pos, cell))


def expand_rules(rules: list[dict], dims: list[Dimension]) -> list[Cell]:
    """De-duplicated union of the checked rules' Cartesian products, unknown ids dropped, canonical order."""
    cells = {cell for r in rules if r.get("run")
             for cell in product(*[[i for i in d.ids if i in set(r.get(d.key) or ())] for d in dims])}
    return sorted(cells, key=_sort_key(dims))


@dataclass(frozen=True)
class Job:
    """One agent's assignment: a batch of cells."""

    slug: str  # unique folder name under runs/<run_id>/
    label: str  # human label (values of the split dimensions)
    cells: tuple[Cell, ...]  # canonical order

    def values(self, index: int) -> tuple[str, ...]:
        """Distinct ids of dimension `index` among this job's cells (canonical order)."""
        return tuple(dict.fromkeys(cell[index] for cell in self.cells))

    @property
    def is_product(self) -> bool:
        """True when the cells are exactly the Cartesian product of their per-dimension values."""
        return bool(self.cells) and len(self.cells) == prod(len(self.values(i)) for i in range(len(self.cells[0])))


def build_jobs(cells: list[Cell], dims: list[Dimension], merge: list[str], max_cells: int) -> list[Job]:
    """Group cells by the non-merged dimensions (one agent per group), then split groups above max_cells."""
    split = [i for i, d in enumerate(dims) if d.key not in set(merge)]
    pos = _sort_key(dims)
    ordered = sorted(cells, key=lambda c: (tuple(pos(c)[i] for i in split), pos(c)))  # group-major order
    jobs, slugs = [], set()
    for key, group in groupby(ordered, key=lambda c: tuple(c[i] for i in split)):
        group = list(group)
        size = max_cells if max_cells > 0 else len(group)
        chunks = [group[n:n + size] for n in range(0, len(group), size)]
        base = " · ".join(dims[i].option(v).label for i, v in zip(split, key)) or "all cells"
        for n, chunk in enumerate(chunks, 1):
            label = f"{base} (part {n}/{len(chunks)})" if len(chunks) > 1 else base
            slug = stem = (slugify(label) or "job")[:60]  # keeps agent file paths under Windows' 260-char limit
            suffix = 1
            while slug in slugs:  # labels that slugify alike get a numeric suffix
                suffix += 1
                slug = f"{stem}-{suffix}"
            slugs.add(slug)
            jobs.append(Job(slug=slug, label=label, cells=tuple(chunk)))
    return jobs


def interval_index(dims: list[Dimension]) -> int | None:
    """Position of the interval dimension, if there is one."""
    return next((i for i, d in enumerate(dims) if d.kind == "interval"), None)


def interval_ranges(today: date, dim: Dimension, ids: tuple[str, ...]) -> dict[str, tuple[date, date]]:
    """Inclusive (start, today) date range for each given interval option."""
    return {i: (today - timedelta(days=dim.option(i).days), today) for i in ids}
