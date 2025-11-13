# chat/admin.py
from django.contrib import admin
from .models import Case, Instruction

class InstructionInline(admin.TabularInline):
    model = Instruction
    extra = 0
    fields = ("stage", "version", "active", "body")
    show_change_link = True

@admin.register(Case)
class CaseAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "updated_at")
    search_fields = ("name", "slug", "content", "prelim_dx_raw")  # <<< dodałem
    prepopulated_fields = {"slug": ("name",)}
    inlines = [InstructionInline]
    fieldsets = (
        ("Podstawowe", {
            "fields": ("name", "slug", "content", "prelim_dx_raw"),  # <<< dodałem
        }),
        ("Kanon ZNORMALIZOWANY (używany w instrukcjach przez {case_norm})", {
            "fields": ("diagnostics_norm", "meds_norm", "reco_norm", "dispo_norm"),
        }),
    )

@admin.register(Instruction)
class InstructionAdmin(admin.ModelAdmin):
    list_display = ("stage", "case", "version", "active", "updated_at")
    list_filter = ("stage", "active", "case")
    search_fields = ("body",)
    autocomplete_fields = ("case",)
