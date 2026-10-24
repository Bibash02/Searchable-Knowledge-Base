from django.conf import settings
from django.db import models


class Visibility(models.TextChoices):
    PUBLIC = "public", "Public"
    INTERNAL = "internal", "Internal"


class Status(models.TextChoices):
    DRAFT = "draft", "Draft"
    PUBLISHED = "published", "Published"
    ARCHIVED = "archived", "Archived"


class Category(models.Model):
    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=100, unique=True)
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "categories"

    def __str__(self):
        return self.name


class Article(models.Model):
    """
    The stable identity of an article (slug, category, visibility, lifecycle state).
    Content lives in immutable ArticleVersion rows; `published_version` is the one
    readers see. Editing never touches what is live until someone publishes.
    """

    slug = models.SlugField(max_length=80, unique=True)
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name="articles")
    visibility = models.CharField(max_length=10, choices=Visibility.choices, default=Visibility.INTERNAL)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT)
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="kb_articles"
    )
    published_version = models.ForeignKey(
        "ArticleVersion", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    # first_published_at is never cleared: it records "this URL was once public",
    # which is what lets us answer 410 Gone instead of 404 after deletion.
    first_published_at = models.DateTimeField(null=True, blank=True)
    last_published_at = models.DateTimeField(null=True, blank=True)
    deleted_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["status", "visibility", "deleted_at"]),
        ]

    def __str__(self):
        return self.slug

    @property
    def latest_version(self):
        # Versions are ordered newest-first; this reuses a prefetch cache when present.
        return next(iter(self.versions.all()), None)


class ArticleVersion(models.Model):
    article = models.ForeignKey(Article, on_delete=models.CASCADE, related_name="versions")
    number = models.PositiveIntegerField()
    title = models.CharField(max_length=200)
    body = models.TextField()
    change_note = models.CharField(max_length=200, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-number"]
        constraints = [
            models.UniqueConstraint(fields=["article", "number"], name="unique_version_number"),
        ]

    def __str__(self):
        return f"{self.article_id} v{self.number}"


class SlugRedirect(models.Model):
    """Old slug -> article. Points at the article id, so renames never form chains."""

    old_slug = models.SlugField(max_length=80, unique=True)
    article = models.ForeignKey(Article, on_delete=models.CASCADE, related_name="redirects")
    created_at = models.DateTimeField(auto_now_add=True)
