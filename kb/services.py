"""
Write-side business rules: content lifecycle lives here, not in views.

    draft ──publish──▶ published ──unpublish──▶ draft
      │                   │
      └──────archive──────┘──▶ archived ──publish──▶ published
    any state ──soft_delete──▶ deleted (hidden everywhere) ──restore──▶ previous state
"""
from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify

from .models import Article, ArticleVersion, SlugRedirect, Status, Visibility

RESERVED_SLUGS = {"search"}  # collides with /articles/search/


class ServiceError(Exception):
    pass


# ---- slugs -----------------------------------------------------------------

def _slug_taken(slug, article=None):
    if slug in RESERVED_SLUGS:
        return True
    others = Article.objects.filter(slug=slug)
    redirects = SlugRedirect.objects.filter(old_slug=slug)
    if article is not None:
        others = others.exclude(pk=article.pk)
        redirects = redirects.exclude(article=article)
    return others.exists() or redirects.exists()


def _generate_slug(title):
    base = slugify(title)[:60].strip("-") or "article"
    slug, n = base, 2
    while _slug_taken(slug):
        slug = f"{base}-{n}"
        n += 1
    return slug


# ---- lifecycle -------------------------------------------------------------

@transaction.atomic
def create_article(*, author, title, body, category, visibility=Visibility.INTERNAL, slug=None, change_note=""):
    """New articles are drafts and internal by default: nothing is public by accident."""
    if slug:
        slug = slugify(slug)
        if _slug_taken(slug):
            raise ServiceError(f"Slug '{slug}' is already in use.")
    else:
        slug = _generate_slug(title)

    article = Article.objects.create(slug=slug, category=category, visibility=visibility, author=author)
    ArticleVersion.objects.create(
        article=article, number=1, title=title, body=body, change_note=change_note, created_by=author
    )
    return article


@transaction.atomic
def save_draft(article, *, user, title=None, body=None, change_note=""):
    """Append a new version if content changed. Never touches the live version."""
    latest = article.versions.order_by("-number").first()
    new_title = latest.title if title is None else title
    new_body = latest.body if body is None else body
    if new_title == latest.title and new_body == latest.body:
        return latest
    version = ArticleVersion.objects.create(
        article=article,
        number=latest.number + 1,
        title=new_title,
        body=new_body,
        change_note=change_note,
        created_by=user,
    )
    article.save(update_fields=["updated_at"])
    return version


@transaction.atomic
def update_metadata(article, *, slug=None, category=None, visibility=None):
    fields = ["updated_at"]
    if category is not None:
        article.category = category
        fields.append("category")
    if visibility is not None:
        article.visibility = visibility
        fields.append("visibility")
    if slug is not None:
        slug = slugify(slug)
        if slug != article.slug:
            if _slug_taken(slug, article):
                raise ServiceError(f"Slug '{slug}' is already in use.")
            # Coming back to a former slug: drop the redirect that would shadow it.
            SlugRedirect.objects.filter(old_slug=slug, article=article).delete()
            SlugRedirect.objects.create(old_slug=article.slug, article=article)
            article.slug = slug
            fields.append("slug")
    article.save(update_fields=fields)
    return article


@transaction.atomic
def publish(article, *, user, version_number=None):
    versions = article.versions
    version = (
        versions.filter(number=version_number).first()
        if version_number is not None
        else versions.order_by("-number").first()
    )
    if version is None:
        raise ServiceError("That version does not exist.")
    now = timezone.now()
    article.status = Status.PUBLISHED
    article.published_version = version
    article.first_published_at = article.first_published_at or now
    article.last_published_at = now
    article.save(update_fields=["status", "published_version", "first_published_at", "last_published_at", "updated_at"])
    return article


def _withdraw(article, status):
    article.status = status
    article.published_version = None
    article.save(update_fields=["status", "published_version", "updated_at"])
    return article


def unpublish(article):
    return _withdraw(article, Status.DRAFT)


def archive(article):
    return _withdraw(article, Status.ARCHIVED)


def soft_delete(article):
    article.deleted_at = timezone.now()
    article.save(update_fields=["deleted_at", "updated_at"])
    return article


def restore(article):
    article.deleted_at = None
    article.save(update_fields=["deleted_at", "updated_at"])
    return article
