from django.db import models
from django.contrib.auth.models import AbstractUser

# Create your models here.
class Role(models.TextChoices):
    READER = "reader", "Reader"  # authenticated, public content only
    STAFF = "staff", "Staff"  # + internal published content
    EDITOR = "editor", "Editor"  # + drafts, archived, write access
    ADMIN = "admin", "Admin"  # + restore deleted content


class User(AbstractUser):
    role = models.CharField(max_length=10, choices=Role.choices, default=Role.READER)