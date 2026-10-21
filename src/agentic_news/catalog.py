"""Catalog: the topics and the four search dimensions, and conversion of table rows into agent jobs.

Local: pure data and pure functions, no I/O. Option IDs (e.g. `viral_tweets`) are stable machine names reused
in prompts, the output schema enums and the dashboard; labels/definitions are for humans and the prompt.
Global context: the dashboard edits rows like {"run", "topic", "intervals", "types", "sources", "variants"};
`build_jobs` turns the checked rows into one Job per topic, and each Job becomes one Codex agent.
"""

import re  # slugify topics into folder-safe names
from dataclasses import dataclass  # immutable Job/Option records
from datetime import date, timedelta  # interval date arithmetic
from math import prod  # number of cells = product of selected option counts


@dataclass(frozen=True)
class Option:
    """One selectable value of a dimension."""

    label: str  # short human label shown in the dashboard
    definition: str  # one-line meaning, copied into the agent prompt


DEFAULT_TOPICS = [  # the user's 24 topics, in the order they were requested
    "AI industry", "AI research", "Mechanistic interpretability", "Physics", "Fundamental physics",
    "Pure math", "Applied math", "AI in math", "AI in physics", "AI for AI research",
    "AI for software engineering", "RSI", "LLMs", "Agents", "Reinforcement learning",
    "Philosophy of science", "AI governance", "Memetic tribes in AI", "Software engineering",
    "Consciousness", "Neuroscience", "General natural science", "General science", "Philosophy",
]

INTERVAL_DAYS = {"day": 1, "week": 7, "month": 30, "year": 365, "decade": 3652, "century": 36524}  # days back

DIMENSIONS: dict[str, dict[str, Option]] = {  # row column -> {option id -> Option}; dict order = display order
    "intervals": {
        "day": Option("Last day", "published in the last 24 hours"),
        "week": Option("Last week", "published in the last 7 days"),
        "month": Option("Last month", "published in the last 30 days"),
        "year": Option("Last year", "published in the last 365 days"),
        "decade": Option("Last 10 years", "landmark, most influential works of the last 10 years"),
        "century": Option("Last 100 years", "landmark, most influential works of the last 100 years"),
    },
    "types": {
        "paper": Option("Papers", "research paper or preprint (arXiv, journal, conference, technical report)"),
        "article": Option("Articles", "news article, blog post, essay or newsletter issue"),
        "book": Option("Books", "book (popular or academic, including textbooks)"),
        "video": Option("Videos", "video (YouTube, recorded talk or lecture, documentary)"),
        "podcast": Option("Podcasts", "podcast episode"),
    },
    "sources": {
        "viral_papers": Option("Viral papers", "papers that drew unusual attention (trending on Hugging Face "
                               "Papers or alphaXiv, high citation velocity, widely discussed by researchers)"),
        "viral_news": Option("Viral news", "stories covered widely by news outlets or high on Hacker News/Reddit"),
        "viral_tweets": Option("Viral tweets", "content that spread on X/Twitter (or Bluesky/Threads) with high "
                               "engagement; the item may be the post itself or what it linked to"),
        "viral_content": Option("Viral internet content", "anything else that spread widely online "
                                "(blog posts, YouTube videos, Substack essays, forum threads)"),
    },
    "variants": {
        "pop_sci": Option("Pop sci", "accessible to a general audience (journalism, explainers, popular books)"),
        "rigorous": Option("Rigorous", "primary or technical source for experts (papers, technical reports, "
                           "textbooks, lectures, expert talks)"),
    },
}
ITEM_FIELD = {"intervals": "interval", "types": "type", "sources": "source", "variants": "variant"}  # row -> item key


@dataclass(frozen=True)
class Job:
    """One topic agent's assignment: the topic plus the selected option IDs per dimension."""

    topic: str  # free text from the table (custom topics allowed)
    slug: str  # unique folder name under runs/<run_id>/
    intervals: tuple[str, ...]
    types: tuple[str, ...]
    sources: tuple[str, ...]
    variants: tuple[str, ...]

    @property
    def cells(self) -> int:
        """How many interval x type x source x variant combinations this agent must cover."""
        return prod(len(getattr(self, dim)) for dim in DIMENSIONS)


def default_rows() -> list[dict]:
    """Seed table: every topic unchecked with a full form (all options of every dimension)."""
    return [{"run": False, "topic": t, **{dim: list(opts) for dim, opts in DIMENSIONS.items()}}
            for t in DEFAULT_TOPICS]


def _slugify(topic: str) -> str:
    """Lowercase, non-alphanumerics collapsed to '-' (safe on Windows and POSIX)."""
    return re.sub(r"[^a-z0-9]+", "-", topic.lower()).strip("-") or "topic"


def build_jobs(rows: list[dict]) -> list[Job]:
    """Checked rows with a topic and at least one known option per dimension -> Jobs with unique slugs."""
    jobs: list[Job] = []
    seen: set[str] = set()  # slugs already used in this run
    for row in rows:
        topic = str(row.get("topic") or "").strip()  # NaN/None from the editor become ""
        picked = {dim: tuple(o for o in opts if o in set(row.get(dim) or ())) for dim, opts in DIMENSIONS.items()}
        if not row.get("run") or not topic or not all(picked.values()):
            continue  # unchecked, blank or incomplete rows launch nothing
        base = slug = _slugify(topic)
        n = 1
        while slug in seen:  # "AI & Math" and "AI  math" both slugify to ai-math
            n += 1
            slug = f"{base}-{n}"
        seen.add(slug)
        jobs.append(Job(topic=topic, slug=slug, **picked))
    return jobs


def interval_ranges(today: date, intervals: tuple[str, ...]) -> dict[str, tuple[date, date]]:
    """Inclusive (start, today) date range for each selected interval."""
    return {i: (today - timedelta(days=INTERVAL_DAYS[i]), today) for i in intervals}
