from django.db.models import Count, Q

from .models import Article, Category, Status, Visibility
from .permissions import can_see_internal, is_editor


def visible_articles(user):
    """
    THE single place that decides which articles a caller may see.

    Every read path (list, detail, search, category counts) starts from this
    queryset, so a search backend can never return something the caller could
    not have fetched directly.
    """
    qs = Article.objects.filter(deleted_at__isnull=True).select_related(
        "category", "published_version", "author"
    )
    if is_editor(user):
        # Editors also work on drafts and archived articles.
        return qs.prefetch_related("versions")

    qs = qs.filter(status=Status.PUBLISHED, published_version__isnull=False)
    if not can_see_internal(user):
        qs = qs.filter(visibility=Visibility.PUBLIC)
    return qs


def search_scope(user):
    """Editors search their latest working copy; everyone else, only what is live."""
    return "latest" if is_editor(user) else "published"


def visible_categories(user):
    """
    Categories annotated with how many articles *this caller* can see.
    Categories with nothing visible are hidden from non-editors, so neither the
    existence nor the size of an internal-only category leaks.
    """
    visible_ids = visible_articles(user).values("pk")
    qs = Category.objects.annotate(
        article_count=Count("articles", filter=Q(articles__pk__in=visible_ids), distinct=True)
    )
    if not is_editor(user):
        qs = qs.filter(article_count__gt=0)
    return qs
