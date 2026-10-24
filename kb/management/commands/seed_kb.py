from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from rest_framework.authtoken.models import Token

from accounts.models import Role
from kb import services
from kb.models import Article, Category, Visibility

USERS = [("reader", Role.READER), ("staff", Role.STAFF), ("editor", Role.EDITOR), ("admin", Role.ADMIN)]

CATEGORIES = {
    "getting-started": "Getting started",
    "billing": "Billing",
    "engineering": "Engineering runbooks",
}

ARTICLES = [
    ("Resetting your password", "Open Settings, choose Security, then press Reset password. A link arrives by email.", "getting-started", Visibility.PUBLIC, True),
    ("Understanding your invoice", "Invoices are issued on the first of each month. Line items show usage and taxes.", "billing", Visibility.PUBLIC, True),
    ("Refund escalation policy", "Refunds above the limit need finance approval. Do not share the threshold with customers.", "billing", Visibility.INTERNAL, True),
    ("Database failover runbook", "Promote the replica, update the connection string, then verify replication lag.", "engineering", Visibility.INTERNAL, True),
    ("Upcoming pricing change (draft)", "Embargoed until the announcement. Pricing tiers will be restructured in Q1.", "billing", Visibility.INTERNAL, False),
]


class Command(BaseCommand):
    help = "Create demo users (password: pass1234), categories and articles."

    def handle(self, *args, **opts):
        User = get_user_model()
        users = {}
        for name, role in USERS:
            user, created = User.objects.get_or_create(username=name, defaults={"role": role})
            if created:
                user.set_password("pass1234")
                user.save()
            token, _ = Token.objects.get_or_create(user=user)
            users[name] = user
            self.stdout.write(f"{name:7} token={token.key}")

        cats = {slug: Category.objects.get_or_create(slug=slug, defaults={"name": n})[0] for slug, n in CATEGORIES.items()}

        if Article.objects.exists():
            self.stdout.write("Articles already exist, skipping.")
            return
        for title, body, cat, visibility, published in ARTICLES:
            article = services.create_article(
                author=users["editor"], title=title, body=body, category=cats[cat], visibility=visibility
            )
            if published:
                services.publish(article, user=users["editor"])
        self.stdout.write(self.style.SUCCESS("Seeded."))
