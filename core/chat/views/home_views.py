from django.shortcuts import render
from ..models import Case
from .utils import STAGE_ORDER

def home_view(request):
    sample_case = Case.objects.order_by("name").first()
    sample_stage = STAGE_ORDER[0] if sample_case else None

    cases = []
    if request.user.is_authenticated:
        cases = Case.objects.order_by("name")[:24]  # ewentualnie .filter(is_published=True)

    return render(
        request,
        "chat/home.html",
        {
            "sample_case": sample_case,
            "sample_stage": sample_stage,
            "features": [
                "Interaktywne etapy diagnostyki z prowadzeniem krok po kroku",
                "Baza przypadków z aktualizowanymi instrukcjami",
                "Śledzenie postępów i możliwość powrotu do poprzednich etapów",
            ],
            "cases": cases,
        },
    )
