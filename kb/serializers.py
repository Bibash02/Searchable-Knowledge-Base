from rest_framework import serializers

from .models import Category, Status, Visibility
from .permissions import is_editor
from .search import make_snippet


class CategorySerializer(serializers.Serializer):
    slug = serializers.CharField()
    name = serializers.CharField()
    description = serializers.CharField()
    article_count = serializers.IntegerField()


class _ArticleReadMixin:
    """Which version a caller sees depends on role: editors the newest, others the live one."""

    def _editor(self):
        return is_editor(self.context["request"].user)

    def _version(self, obj):
        return obj.latest_version if self._editor() else obj.published_version


class ArticleListSerializer(_ArticleReadMixin, serializers.ModelSerializer):
    title = serializers.SerializerMethodField()
    summary = serializers.SerializerMethodField()
    category = serializers.SerializerMethodField()
    snippet = serializers.SerializerMethodField()
    score = serializers.SerializerMethodField()
    status = serializers.SerializerMethodField()

    class Meta:
        from .models import Article

        model = Article
        fields = [
            "slug", "title", "summary", "category", "visibility", "status",
            "first_published_at", "last_published_at", "snippet", "score",
        ]

    def to_representation(self, instance):
        data = super().to_representation(instance)
        # Keep response shapes stable: optional keys are dropped, not nulled inconsistently.
        if not self.context.get("query"):
            data.pop("snippet", None)
            data.pop("score", None)
        if not self._editor():
            data.pop("status", None)
        return data

    def get_title(self, obj):
        return self._version(obj).title

    def get_summary(self, obj):
        body = " ".join(self._version(obj).body.split())
        return body[:200] + ("…" if len(body) > 200 else "")

    def get_category(self, obj):
        return {"slug": obj.category.slug, "name": obj.category.name}

    def get_snippet(self, obj):
        return make_snippet(self._version(obj).body, self.context.get("query", ""))

    def get_score(self, obj):
        return getattr(obj, "score", None)

    def get_status(self, obj):
        return obj.status


class ArticleDetailSerializer(ArticleListSerializer):
    body = serializers.SerializerMethodField()
    version = serializers.SerializerMethodField()
    published_version = serializers.SerializerMethodField()

    class Meta(ArticleListSerializer.Meta):
        fields = [
            "slug", "title", "body", "category", "visibility", "status", "version",
            "published_version", "first_published_at", "last_published_at",
        ]

    def to_representation(self, instance):
        data = super().to_representation(instance)
        if not self._editor():
            data.pop("published_version")
        return data

    def get_body(self, obj):
        return self._version(obj).body

    def get_version(self, obj):
        return self._version(obj).number

    def get_published_version(self, obj):
        return obj.published_version.number if obj.published_version else None


class VersionSerializer(serializers.Serializer):
    number = serializers.IntegerField()
    title = serializers.CharField()
    body = serializers.CharField()
    change_note = serializers.CharField()
    created_by = serializers.SerializerMethodField()
    created_at = serializers.DateTimeField()

    def get_created_by(self, obj):
        return obj.created_by.get_username() if obj.created_by else None


class ArticleWriteSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=200, required=False)
    body = serializers.CharField(required=False)
    category = serializers.SlugRelatedField(slug_field="slug", queryset=Category.objects.all(), required=False)
    visibility = serializers.ChoiceField(choices=Visibility.choices, required=False)
    slug = serializers.SlugField(max_length=80, required=False)
    change_note = serializers.CharField(max_length=200, required=False, allow_blank=True)

    def validate(self, attrs):
        if self.context.get("creating"):
            missing = [f for f in ("title", "body", "category") if f not in attrs]
            if missing:
                raise serializers.ValidationError({f: "This field is required." for f in missing})
        return attrs


class PublishSerializer(serializers.Serializer):
    version = serializers.IntegerField(required=False, min_value=1)
