from rest_framework.routers import DefaultRouter

from .views import ArticleViewSet, CategoryViewSet

router = DefaultRouter()
router.register("articles", ArticleViewSet, basename="article")
router.register("categories", CategoryViewSet, basename="category")

urlpatterns = router.urls
