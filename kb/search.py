"""
Search backends.

Contract (this is what makes search a permissions problem, not just a query box):

    backend.search(queryset, query, scope) -> queryset annotated with `score`

`queryset` is ALWAYS already filtered by selectors.visible_articles(user). A backend
may narrow and rank it but must never widen it. When you move to an external engine
(Elasticsearch, Meilisearch, Postgres FTS...), keep that rule: let the engine return
candidate ids, then intersect them with the visible queryset before returning, so a
stale or misconfigured index cannot leak a draft or internal article.

`scope` says which content to match: "published" (the live version) or
"latest" (the newest working copy, for editors).
"""
import re
from importlib import import_module

from django.conf import settings
from django.db.models import Case, IntegerField, OuterRef, Q, Subquery, Value, When

from .models import ArticleVersion

TITLE_WEIGHT = 3
BODY_WEIGHT = 1
EXACT_TITLE_BONUS = 5
MAX_TERMS = 8
MIN_TERM_LENGTH = 2


def tokenize(query):
    seen, terms = set(), []
    for term in re.findall(r"\w+", query.lower()):
        if len(term) >= MIN_TERM_LENGTH and term not in seen:
            seen.add(term)
            terms.append(term)
    return terms[:MAX_TERMS]


class SearchBackend:
    def search(self, queryset, query, scope):
        raise NotImplementedError


class DatabaseSearchBackend(SearchBackend):
    """AND-match every term in title or body; rank title hits above body hits."""

    def search(self, queryset, query, scope):
        terms = tokenize(query)
        if not terms:
            return queryset.none()

        if scope == "latest":
            newest = ArticleVersion.objects.filter(article=OuterRef("pk")).order_by("-number")
            queryset = queryset.annotate(
                _title=Subquery(newest.values("title")[:1]),
                _body=Subquery(newest.values("body")[:1]),
            )
            title_f, body_f = "_title", "_body"
        else:
            title_f, body_f = "published_version__title", "published_version__body"

        score = Value(0, output_field=IntegerField())
        for term in terms:
            in_title = Q(**{f"{title_f}__icontains": term})
            in_body = Q(**{f"{body_f}__icontains": term})
            queryset = queryset.filter(in_title | in_body)
            score = score + Case(
                When(in_title, then=Value(TITLE_WEIGHT)), default=Value(0), output_field=IntegerField()
            )
            score = score + Case(
                When(in_body, then=Value(BODY_WEIGHT)), default=Value(0), output_field=IntegerField()
            )

        exact = Case(
            When(Q(**{f"{title_f}__iexact": query.strip()}), then=Value(EXACT_TITLE_BONUS)),
            default=Value(0),
            output_field=IntegerField(),
        )
        return queryset.annotate(score=score + exact)


def get_backend():
    module_path, class_name = settings.KB_SEARCH_BACKEND.rsplit(".", 1)
    return getattr(import_module(module_path), class_name)()


def make_snippet(text, query, width=160):
    """A short excerpt around the first matching term, for result lists."""
    flat = " ".join(text.split())
    lowered = flat.lower()
    for term in tokenize(query):
        idx = lowered.find(term)
        if idx != -1:
            start = max(0, idx - width // 3)
            end = min(len(flat), start + width)
            prefix = "…" if start > 0 else ""
            suffix = "…" if end < len(flat) else ""
            return f"{prefix}{flat[start:end].strip()}{suffix}"
    return flat[:width] + ("…" if len(flat) > width else "")
