from django.http import JsonResponse, Http404
from django.shortcuts import render, redirect, get_object_or_404
from ..models import Case, CaseHistory
from .utils import (
    STAGES,
    STAGE_ORDER,
    LABELS,
    _bot_reply_stage_db,
    _check_can_proceed,
    generate_summary_assessment,
)


def stage_view(request, case_slug: str, stage: str):
    if stage not in STAGES:
        raise Http404("Nieznany etap")

    case = get_object_or_404(Case, slug=case_slug)
    cfg = STAGES[stage]

    # zmiana przypadku => czyścimy stan poprzedniego
    active_case = request.session.get("active_case_slug")
    if active_case != case.slug:
        request.session["active_case_slug"] = case.slug
        request.session["chats"] = {}
        request.session["completed_stages"] = []
        request.session["can_proceed_to_dx"] = False
        request.session["case_saved"] = False
        request.session.modified = True

    # Stan w sesji
    chats = request.session.get("chats", {})
    completed_stages = request.session.get("completed_stages", [])
    chat = chats.get(stage, [])
    stage_completed = stage in completed_stages

    # prev/next
    idx = STAGE_ORDER.index(stage)
    prev_stage = STAGE_ORDER[idx - 1] if idx > 0 else None
    next_stage = STAGE_ORDER[idx + 1] if idx < len(STAGE_ORDER) - 1 else None

    # --- SPEC: PODSUMOWANIE ---
    if stage == "summary":
        core_stages = [s for s in STAGE_ORDER if s != "summary"]
        missing = [s for s in core_stages if s not in completed_stages]
        if missing:
            return redirect("chat-stage", case_slug=case.slug, stage=missing[0])

        summary_payload = generate_summary_assessment(case, chats)

        # >>> AUTO-ZAPIS: gdy użytkownik wchodzi na summary, traktujemy to jak zakończenie podejścia
        case_saved = request.session.get("case_saved", False)
        if request.user.is_authenticated and not case_saved:
            # dołączamy do czatu krótki blok podsumowania (bez raw)
            chats_to_save = dict(chats)  # kopia
            try:
                data = summary_payload.get("data", {}) or {}
            except Exception:
                data = {}
            chats_to_save["__summary__"] = {
                "verdict": data.get("verdict", ""),
                "summary": data.get("summary", ""),
                "score": data.get("score", None),
            }

            CaseHistory.objects.create(
                user=request.user,
                case=case,
                chats=chats_to_save,
                completed_stages=list(completed_stages or []),
                is_completed=True,
            )
            request.session["case_saved"] = True
            request.session.modified = True
            case_saved = True
        # <<< AUTO-ZAPIS

        return render(
            request,
            cfg["template"],  # "chat/summary.html"
            {
                "case": case,
                "stage": stage,
                "stage_label": LABELS.get(stage, stage.title()),
                "completed_stages": completed_stages,
                "chats": chats,
                "prev_stage": prev_stage,
                "next_stage": next_stage,
                "case_saved": request.session.get("case_saved", False),
                "STAGE_ORDER": STAGE_ORDER,
                "LABELS": LABELS,
                "summary_payload": summary_payload,
            },
        )

    # --- STANDARDOWE ETAPY (GET/POST) ---
    if request.method == "GET":
        return render(
            request,
            cfg["template"],  # "chat/stage.html"
            {
                "chat": chat,
                "can_proceed_to_dx": bool(stage_completed),
                "stage_completed": stage_completed,
                "completed_stages": completed_stages,
                "case": case,
                "stage": stage,
                "stage_label": LABELS.get(stage, stage.title()),
                "prev_stage": prev_stage,
                "next_stage": next_stage,
            },
        )

    # POST — jeśli etap ukończony, nie przyjmujemy nowych wiadomości
    if stage_completed:
        if request.headers.get("x-requested-with") == "XMLHttpRequest" or request.POST.get("ajax") == "1":
            return JsonResponse({"ok": False, "error": "stage_completed"}, status=200)
        return redirect("chat-stage", case_slug=case.slug, stage=stage)

    # Generowanie odpowiedzi
    msg = (request.POST.get("message") or "").strip()
    user_only = [m["text"] for m in chat if m["role"] == "user"]
    bot_only  = [m["text"] for m in chat if m["role"] == "assistant"]

    bot_text = ""
    updated_completed = False

    if msg:
        chat.append({"role": "user", "text": msg})
        bot_text = _bot_reply_stage_db(stage, case, msg, user_only, bot_only, msg)
        chat.append({"role": "assistant", "text": bot_text})

        chats[stage] = chat
        request.session["chats"] = chats

        if _check_can_proceed(bot_text, cfg["targets_done"]):
            if stage not in completed_stages:
                completed_stages.append(stage)
                request.session["completed_stages"] = completed_stages
            request.session["can_proceed_to_dx"] = True
            updated_completed = True

    request.session.modified = True

    # AJAX → JSON
    if request.headers.get("x-requested-with") == "XMLHttpRequest" or request.POST.get("ajax") == "1":
        return JsonResponse({
            "ok": True,
            "bot_text": bot_text,
            "stage_completed": updated_completed or (stage in completed_stages),
        }, status=200)

    return redirect("chat-stage", case_slug=case.slug, stage=stage)
