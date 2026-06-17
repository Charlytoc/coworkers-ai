from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.db import models
from model_utils.models import TimeStampedModel

from core.managers import UserManager
from core.models.organization import Organization


class User(AbstractBaseUser, PermissionsMixin, TimeStampedModel):
    email = models.EmailField(
        verbose_name="email address",
        max_length=255,
        unique=True,
    )
    first_name = models.CharField(max_length=100, null=True, blank=True)
    last_name = models.CharField(max_length=100, null=True, blank=True)
    profile_picture = models.ImageField(
        upload_to='users/profile_pictures/',
        null=True,
        blank=True,
        help_text="Profile picture of the user"
    )
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    onboarding_completed = models.BooleanField(default=False)
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="members"
    )

    objects = UserManager()

    USERNAME_FIELD = "email"

    def __str__(self):
        return self.email

    def save(self, *args, **kwargs):
        # Normalize name fields
        if self.first_name is not None:
            self.first_name = self.first_name.strip() or None
        if self.last_name is not None:
            self.last_name = self.last_name.strip() or None

        # Check if organization is inactive
        if self.organization and self.organization.status == Organization.Status.INACTIVE:
            raise ValueError(f"Organization is inactive: {self.organization.name} ({self.organization.id})")

        super().save(*args, **kwargs)