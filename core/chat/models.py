from django.db import models
from django.utils import timezone
from django.utils.text import slugify
from django.conf import settings


class Case(models.Model):
    """
    Pojedynczy przypadek kliniczny + treści kanoniczne (oryginalne) i znormalizowane per etap.
    """
    STAGE_CHOICES = [
        ("diagnostics", "Diagnostyka"),
        ("first_exam", "Rozpoznanie wstępne"),
        ("meds", "Leczenie ostre"),
        ("reco", "Zalecenia"),
        ("dispo", "Skierowanie / Dispo"),
    ]

    slug = models.SlugField(max_length=120, unique=True)
    name = models.CharField(max_length=200, unique=True)

    # Treść ogólna / opis case’u
    content = models.TextField(blank=True, default="")

    # Kanon ZNORMALIZOWANY per etap (do podstawienia w instrukcję; oddzielony od raw zgodnie z Twoją prośbą)
    diagnostics_norm = models.TextField(blank=True, default="")
    prelim_dx_raw = models.TextField(blank=True, default="")
    meds_norm = models.TextField(blank=True, default="")
    reco_norm = models.TextField(blank=True, default="")
    dispo_norm = models.TextField(blank=True, default="")

    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)[:120]
        return super().save(*args, **kwargs)


class Instruction(models.Model):
    """
    Instrukcja renderowana jako prompt szablonowy dla danego etapu.
    Jeśli 'case' = null → globalny szablon domyślny dla etapu.
    Jeśli istnieje wpis powiązany z case → nadpisuje globalny.
    """
    STAGE_CHOICES = [
        ("diagnostics", "Diagnostyka"),
        ("first_exam", "Rozpoznanie wstępne"),
        ("meds", "Leczenie ostre"),
        ("reco", "Zalecenia"),
        ("dispo", "Skierowanie / Dispo"),
    ]

    case = models.ForeignKey(Case, null=True, blank=True, on_delete=models.CASCADE, related_name="instructions")
    stage = models.CharField(max_length=32, choices=STAGE_CHOICES)
    body = models.TextField(help_text="Szablon instrukcji z placeholderami: {case_norm}, {user_answers}, {bot_answers}, {actual_msg}")
    active = models.BooleanField(default=True)
    version = models.PositiveIntegerField(default=1)

    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-active", "-version", "-created_at"]

    def __str__(self) -> str:
        scope = self.case.name if self.case_id else "GLOBAL"
        return f"[{scope}] {self.get_stage_display()} v{self.version} ({'active' if self.active else 'inactive'})"


class CaseHistory(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="case_histories")
    case = models.ForeignKey(Case, on_delete=models.CASCADE, related_name="histories")
    created_at = models.DateTimeField(auto_now_add=True)

    # zapisujemy sesyjny stan
    chats = models.JSONField(default=dict)              # {"diagnostics":[...], "first_exam":[...], ...}
    completed_stages = models.JSONField(default=list)   # ["diagnostics", ...]
    is_completed = models.BooleanField(default=True)    # flaga zaliczenia

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.user} · {self.case.name} · {self.created_at:%Y-%m-%d %H:%M}"
