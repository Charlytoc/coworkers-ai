"""Workspace-scoped media stored via Django ``FileField`` (local or default storage / S3)."""

from __future__ import annotations

import mimetypes
import re
import uuid
from pathlib import Path
from urllib.parse import urljoin

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from model_utils.models import TimeStampedModel

from core.models.workspace import Workspace

_SHA256_RE = re.compile(r"^[a-f0-9]{64}$", re.IGNORECASE)

_DANGEROUS_SUFFIXES = frozenset(
    {
        ".exe",
        ".bat",
        ".cmd",
        ".com",
        ".pif",
        ".scr",
        ".vbs",
        ".js",
        ".jar",
        ".app",
        ".deb",
        ".rpm",
        ".dmg",
        ".pkg",
        ".msi",
    }
)


def media_object_upload_to(instance: "MediaObject", filename: str) -> str:
    """Stable, collision-resistant path under the workspace (works with local disk or S3 default storage)."""
    wid = instance.workspace_id or "no_workspace"
    path = Path(filename)
    ext = (path.suffix or "").lower()[:20]
    safe = path.stem[:80] if path.stem else "file"
    return f"workspaces/{wid}/{timezone.now():%Y/%m}/{uuid.uuid4().hex}_{safe}{ext}"


class MediaObject(TimeStampedModel):
    """Binary asset in storage. Use ``extra`` for origin, dimensions, duration, provider ids, etc."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    workspace = models.ForeignKey(
        Workspace,
        on_delete=models.CASCADE,
        related_name="media_objects",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="uploaded_media_objects",
    )

    title = models.CharField(
        max_length=200,
        blank=True,
        help_text="Optional display name; falls back to original_filename when empty.",
    )

    file = models.FileField(upload_to=media_object_upload_to, max_length=512)

    original_filename = models.CharField(max_length=255, blank=True)
    byte_size = models.BigIntegerField(null=True, blank=True)
    mime_type = models.CharField(max_length=127, blank=True)
    checksum_sha256 = models.CharField(
        max_length=64,
        blank=True,
        db_index=True,
        help_text=(
            "Optional hex SHA-256 of file bytes: dedupe/idempotency, verify download vs source, "
            "detect storage corruption or accidental overwrite."
        ),
    )

    extra = models.JSONField(
        default=dict,
        blank=True,
        help_text="Flexible metadata: e.g. origin (upload/generated/…), width, height, duration_ms, provider, model.",
    )

    is_public = models.BooleanField(default=False)

    class Meta:
        ordering = ("-created",)
        indexes = [
            models.Index(fields=("workspace", "-created")),
        ]

    def __str__(self) -> str:
        label = self.title or self.original_filename or str(self.pk)
        return str(label)

    @property
    def display_name(self) -> str:
        return (self.title or self.original_filename or "").strip() or str(self.pk)

    @property
    def extension(self) -> str:
        name = self.original_filename or (self.file.name if self.file else "") or ""
        return Path(name).suffix.lower()

    @property
    def is_image(self) -> bool:
        return bool(self.mime_type and self.mime_type.startswith("image/"))

    def clean(self) -> None:
        super().clean()
        if self.checksum_sha256 and not _SHA256_RE.match(self.checksum_sha256):
            raise ValidationError({"checksum_sha256": "Must be 64 lowercase hex characters."})
        if self.checksum_sha256:
            self.checksum_sha256 = self.checksum_sha256.lower()

        if not self.file:
            raise ValidationError({"file": "A file is required."})

        name_for_scan = ""
        if getattr(self.file, "name", None):
            name_for_scan = self.file.name
        elif self.original_filename:
            name_for_scan = self.original_filename
        if name_for_scan and Path(name_for_scan).suffix.lower() in _DANGEROUS_SUFFIXES:
            raise ValidationError({"original_filename": "This file extension is not allowed for security reasons."})

    def save(self, *args, **kwargs) -> None:
        self._sync_from_file()
        self.full_clean()
        super().save(*args, **kwargs)

    def _sync_from_file(self) -> None:
        if not self.file:
            return
        try:
            size = self.file.size
        except (FileNotFoundError, OSError, ValueError):
            return
        if self.byte_size is None:
            self.byte_size = size
        if not self.original_filename and self.file.name:
            self.original_filename = Path(self.file.name).name
        if not self.mime_type:
            guessed, _ = mimetypes.guess_type(self.file.name)
            if guessed:
                self.mime_type = guessed

    def resolve_public_url(self) -> str | None:
        """Return a browser-usable URL when bytes are served via ``FileField`` (local or default storage URL)."""
        if not self.file:
            return None
        url = self.file.url
        if url.startswith(("http://", "https://")):
            return url
        base = str(getattr(settings, "SITE_URL", "") or "").rstrip("/")
        if not base:
            return url
        return urljoin(f"{base}/", url.lstrip("/"))
