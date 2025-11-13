from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.shortcuts import render, redirect, get_object_or_404
from ..models import Case, CaseHistory
from django.db.models import Count, Max

@login_required
def history_list_view(request):
    items = CaseHistory.objects.filter(user=request.user).select_related("case")
    return render(request, "chat/history_list.html", {"items": items})

@require_POST
def reset_case_view(request, case_slug: str):
    case = get_object_or_404(Case, slug=case_slug)
    # wyczyść stan tylko dla aktywnego case'a
    request.session["active_case_slug"] = case.slug
    request.session["chats"] = {}
    request.session["completed_stages"] = []
    request.session["can_proceed_to_dx"] = False
    request.session["case_saved"] = False
    request.session.modified = True
    return redirect("chat-stage", case_slug=case.slug, stage="diagnostics")


@login_required
def completed_grouped(request):
    """
    „Foldery” per Case — zlicza podejścia użytkownika do każdego case'a.
    """
    groups = (
        CaseHistory.objects
        .filter(user=request.user)
        .values('case', 'case__name', 'case__slug')
        .annotate(total=Count('id'), last_time=Max('created_at'))
        .order_by('case__name')
    )
    return render(request, 'chat/completed_grouped.html', {'groups': groups})


@login_required
def completed_case(request, case_slug: str):
    """
    Lista podejść (histories) dla konkretnego case'a.
    """
    case = get_object_or_404(Case, slug=case_slug)
    items = (
        CaseHistory.objects
        .filter(user=request.user, case=case)
        .order_by('-created_at')
    )
    return render(request, 'chat/completed_case.html', {'case': case, 'items': items})


@login_required
def completed_detail(request, pk: int):
    """
    Szczegóły jednego podejścia – werdykt + cała rozmowa.
    """
    item = get_object_or_404(CaseHistory, pk=pk, user=request.user)
    summary_meta = item.chats.get('__summary__', {})
    return render(request, 'chat/completed_detail.html', {
        'item': item,
        'summary_meta': summary_meta,
    })
