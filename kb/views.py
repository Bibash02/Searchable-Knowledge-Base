from django.http import Http404
from django.urls import reverse
from rest_framework import status as http
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import APIException, PermissionDenied, ValidationError
from rest_framework.response import Response

from . import services
from .models import Article, SlugRedirect, Status, Visibility
from .permissions import EditorWritesOnly, can_see_internal, is_admin, is_editor
from .search import get_backend
from .selectors import search_scope, visible_articles, visible_categories
from .serializers import (ArticleDetailSerializer, ArticleListSerializer, ArticleWriteSerializer, CategorySerializer, PublishSerializer, VersionSerializer,)

READER_ORDERINGS = {"title", "-title", "last_published_at", "-last_published_at"}
EDITOR_ORDERINGS = READER_ORDERINGS | {"updated_at", "-updated_at"}


class Gone(APIException):
    status_code = http.HTTP_410_GONE
    default_detail = "This article has been removed."
    default_code = "gone"


class CategoryViewSet(viewsets.GenericViewSet):
    lookup_field = "slug"

    def list(self, request):
        data = CategorySerializer(visible_categories(request.user), many=True).data
        return Response(data)


class ArticleViewSet(viewsets.GenericViewSet):
    lookup_field = "slug"
    lookup_value_regex = r"[-\w]+"
    permission_classes = [EditorWritesOnly]

    # ---- plumbing ----------------------------------------------------------

    def get_queryset(self):
        return visible_articles(self.request.user)

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        ctx["query"] = self.request.query_params.get("q", "").strip()
        return ctx

    def get_object(self):
        """Visible articles only: hidden ones are indistinguishable from missing ones."""
        try:
            return self.get_queryset().get(slug=self.kwargs["slug"])
        except Article.DoesNotExist:
            raise Http404

    def _detail(self, article, code=http.HTTP_200_OK):
        article = self.get_queryset().get(pk=article.pk)  # re-fetch with the right select/prefetch
        return Response(ArticleDetailSerializer(article, context=self.get_serializer_context()).data, status=code)

    # ---- reads -------------------------------------------------------------

    def list(self, request):
        user = request.user
        params = request.query_params
        qs = self.get_queryset()

        if category := params.get("category"):
            qs = qs.filter(category__slug=category)
        if is_editor(user) and (st := params.get("status")) in Status.values:
            qs = qs.filter(status=st)
        if can_see_internal(user) and (vis := params.get("visibility")) in Visibility.values:
            qs = qs.filter(visibility=vis)

        default = ("-updated_at",) if is_editor(user) else ("-last_published_at",)
        allowed = EDITOR_ORDERINGS if is_editor(user) else READER_ORDERINGS
        requested = params.get("ordering")
        ordering = (requested,) if requested in allowed else default

        query = params.get("q", "").strip()
        if query:
            qs = get_backend().search(qs, query, search_scope(user))
            # Relevance first unless the caller explicitly asked for another order.
            ordering = ((requested,) if requested in allowed else ("-score",)) + default
        qs = qs.order_by(*ordering, "id")

        page = self.paginate_queryset(qs)
        data = ArticleListSerializer(page, many=True, context=self.get_serializer_context()).data
        return self.get_paginated_response(data)

    @action(detail=False, methods=["get"], url_path="search")
    def search(self, request):
        if len(request.query_params.get("q", "").strip()) < 2:
            raise ValidationError({"q": "Enter at least 2 characters."})
        return self.list(request)

    def retrieve(self, request, slug=None):
        article = self.get_queryset().filter(slug=slug).first()
        if article is not None:
            return Response(ArticleDetailSerializer(article, context=self.get_serializer_context()).data)

        # Renamed? Only redirect if the caller may actually see the target.
        redirect = SlugRedirect.objects.filter(old_slug=slug).select_related("article").first()
        if redirect and self.get_queryset().filter(pk=redirect.article_id).exists():
            location = request.build_absolute_uri(reverse("article-detail", kwargs={"slug": redirect.article.slug}))
            return Response(status=http.HTTP_301_MOVED_PERMANENTLY, headers={"Location": location})

        # Deleted? 410 only for URLs that were once public, so internal and
        # never-published slugs can't be probed for existence.
        if Article.objects.filter(
            slug=slug,
            deleted_at__isnull=False,
            visibility=Visibility.PUBLIC,
            first_published_at__isnull=False,
        ).exists():
            raise Gone
        raise Http404

    @action(detail=True, methods=["get"])
    def versions(self, request, slug=None):
        if not is_editor(request.user):
            raise Http404
        article = self.get_object()
        return Response(VersionSerializer(article.versions.all(), many=True).data)

    # ---- writes (editors only; see EditorWritesOnly) -----------------------

    def create(self, request):
        ser = ArticleWriteSerializer(data=request.data, context={"creating": True})
        ser.is_valid(raise_exception=True)
        d = ser.validated_data
        try:
            article = services.create_article(
                author=request.user,
                title=d["title"],
                body=d["body"],
                category=d["category"],
                visibility=d.get("visibility", Visibility.INTERNAL),
                slug=d.get("slug"),
                change_note=d.get("change_note", ""),
            )
        except services.ServiceError as exc:
            raise ValidationError({"slug": str(exc)})
        return self._detail(article, http.HTTP_201_CREATED)

    def partial_update(self, request, slug=None):
        article = self.get_object()
        ser = ArticleWriteSerializer(data=request.data, partial=True)
        ser.is_valid(raise_exception=True)
        d = ser.validated_data
        try:
            services.update_metadata(
                article, slug=d.get("slug"), category=d.get("category"), visibility=d.get("visibility")
            )
        except services.ServiceError as exc:
            raise ValidationError({"slug": str(exc)})
        if "title" in d or "body" in d:
            services.save_draft(
                article,
                user=request.user,
                title=d.get("title"),
                body=d.get("body"),
                change_note=d.get("change_note", ""),
            )
        return self._detail(article)

    def destroy(self, request, slug=None):
        services.soft_delete(self.get_object())
        return Response(status=http.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=["post"])
    def publish(self, request, slug=None):
        article = self.get_object()
        ser = PublishSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        try:
            services.publish(article, user=request.user, version_number=ser.validated_data.get("version"))
        except services.ServiceError as exc:
            raise ValidationError({"version": str(exc)})
        return self._detail(article)

    @action(detail=True, methods=["post"])
    def unpublish(self, request, slug=None):
        article = self.get_object()
        services.unpublish(article)
        return self._detail(article)

    @action(detail=True, methods=["post"])
    def archive(self, request, slug=None):
        article = self.get_object()
        services.archive(article)
        return self._detail(article)

    @action(detail=True, methods=["post"])
    def restore(self, request, slug=None):
        if not is_admin(request.user):
            raise PermissionDenied("Only admins can restore deleted articles.")
        article = Article.objects.filter(slug=slug, deleted_at__isnull=False).first()
        if article is None:
            raise Http404
        services.restore(article)
        return self._detail(article)
