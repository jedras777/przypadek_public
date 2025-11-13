from __future__ import annotations

import json
import logging
import re
import textwrap
import unicodedata

from django.conf import settings
from django.http import Http404
from openai import OpenAI
from openai import AuthenticationError, OpenAIError

from ..models import Case
from ..services import resolve_instruction, render_instruction_body

logger = logging.getLogger(__name__)

# ---------- KONFIGURACJA OPENAI ----------
OPENAI_MODEL_PRIMARY = "gpt-4.1"
OPENAI_MODEL_FALLBACK = "gpt-4.1-mini"


def _make_openai_client() -> OpenAI:
    api_key = getattr(settings, "OPENAI_API_KEY", None)
    if not api_key:
        raise RuntimeError("Brak OPENAI_API_KEY w konfiguracji serwera.")
    return OpenAI(api_key=api_key)


def _call_openai_with_fallback(*, instructions: str, input_text: str, max_tokens: int = 500):
    """
    Próbuje z modelem głównym, a w razie 404/invalid/permission — z fallbackiem.
    Zwraca string (tekst odpowiedzi) albo podnosi wyjątek (łapany wyżej).
    """
    client = _make_openai_client()

    def _extract_text(resp) -> str:
        text = getattr(resp, "output_text", None)
        if text:
            return text
        try:
            return resp.output[0].content[0].text
        except Exception:
            return str(resp)

    # 1) spróbuj modelem głównym
    try:
        resp = client.responses.create(
            model=OPENAI_MODEL_PRIMARY,
            instructions=instructions,
            input=input_text,
            max_output_tokens=max_tokens,
        )
        return _extract_text(resp)
    except OpenAIError as e:
        # Brak dostępu do modelu / niewłaściwy model → spróbuj fallbackiem
        msg = str(e).lower()
        recoverable = any(k in msg for k in ["not found", "unsupported", "permission", "does not exist", "unknown model"])
        if not recoverable:
            raise

    # 2) fallback
    resp = client.responses.create(
        model=OPENAI_MODEL_FALLBACK,
        instructions=instructions,
        input=input_text,
        max_output_tokens=max_tokens,
    )
    return _extract_text(resp)


# ---------- UTIL ----------
def _strip_accents(s: str) -> str:
    if not s:
        return ""
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def _check_can_proceed(bot_text: str, targets) -> bool:
    if not bot_text:
        return False
    txt = _strip_accents(bot_text).lower()
    return any(_strip_accents(t).lower() in txt for t in targets)


# ---------- ETAPY (wspólny template + kolejność + etykiety) ----------
STAGE_ORDER = ["diagnostics", "first_exam", "meds", "reco", "dispo", "summary"]

LABELS = {
    "diagnostics": "Diagnostyka",
    "first_exam": "Rozpoznanie wstępne",
    "meds": "Leczenie ostre",
    "reco": "Zalecenia po leczeniu",
    "dispo": "Skierowanie / Dispo",
    "summary": "Podsumowanie",
}

STAGES = {
    s: {
        "template": "chat/stage.html",   # JEDEN wspólny szablon
        "targets_done": ["zaliczam"],    # fraza zaliczenia w odpowiedzi bota
    }
    for s in STAGE_ORDER
}
# override tylko dla "summary"
STAGES["summary"]["template"] = "chat/summary.html"
STAGES["summary"]["targets_done"] = []


# ---------- RENDEROWANIE INSTRUKCJI Z BAZY ----------
def _render_instruction_from_db(stage, case, user_text, user_answers, bot_answers, actual_msg):
    inst = resolve_instruction(stage, case)
    if not inst:
        raise Http404(f"Brak aktywnej instrukcji dla etapu '{stage}'.")
    return render_instruction_body(
        inst, case,
        user_answers=user_answers,
        bot_answers=bot_answers,
        actual_msg=actual_msg,
    )


def _bot_reply_stage_db(stage: str, case: Case, user_text: str, user_answers, bot_answers, actual_msg) -> str:
    """
    Zwraca tekst odpowiedzi bota lub czytelny komunikat błędu (bez 500).
    """
    try:
        instructions = _render_instruction_from_db(stage, case, user_text, user_answers, bot_answers, actual_msg)
        if getattr(settings, "DEBUG", False):
            # Podgląd promptu tylko w dev
            print(instructions)
        return _call_openai_with_fallback(instructions=instructions, input_text=user_text, max_tokens=500)
    except AuthenticationError:
        return ("Błąd uwierzytelnienia z OpenAI. Sprawdź `OPENAI_API_KEY` w .env "
                "i uprawnienia do modelu w konsoli OpenAI.")
    except OpenAIError as e:
        logger.exception("Błąd OpenAI podczas generowania odpowiedzi etapu: %s", e)
        return "Błąd usługi OpenAI. Spróbuj ponownie za chwilę."
    except RuntimeError as e:
        # np. brak OPENAI_API_KEY
        return f"Konfiguracja: {e}"
    except Exception as e:
        logger.exception("Nieoczekiwany błąd bota: %s", e)
        return "Wewnętrzny błąd bota. Spróbuj ponownie."


def _build_stage_payload(chats):
    payload = []
    for stage in STAGE_ORDER:
        if stage == "summary":
            continue
        messages = chats.get(stage, []) or []
        payload.append(
            {
                "stage": stage,
                "label": LABELS.get(stage, stage.title()),
                "conversation": messages,
                "user_last_answer": next(
                    (m.get("text", "") for m in reversed(messages) if m.get("role") == "user"),
                    "",
                ),
                "assistant_last_answer": next(
                    (m.get("text", "") for m in reversed(messages) if m.get("role") == "assistant"),
                    "",
                ),
            }
        )
    return payload


def _build_transcript(stage_payload):
    sections = []
    for stage in stage_payload:
        lines = [f"## {stage['label']}"]
        for msg in stage["conversation"]:
            role = msg.get("role", "").upper()
            text = msg.get("text", "")
            lines.append(f"{role}: {text}")
        sections.append("\n".join(lines))
    return "\n\n".join(sections).strip()


def _extract_json_payload(raw_text: str):
    if not raw_text:
        return None

    text = raw_text.strip()
    if text.startswith("```"):
        # usuń znacznik kodu (```json ... ```)
        text = re.sub(r"^```[a-zA-Z]*\n", "", text)
        text = text.rsplit("```", 1)[0]

    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        logger.warning("Nie udało się sparsować JSON z odpowiedzi modelu: %s", text)
        return None


SUMMARY_PROMPT_TEMPLATE = textwrap.dedent(
    """
    Jesteś klinicznym egzaminatorem oceniającym przebieg symulacji medycznej w języku polskim.
    Otrzymujesz pełen opis przypadku, kanoniczne odpowiedzi instruktora oraz kompletną transkrypcję rozmowy użytkownika z asystentem na kolejnych etapach.

    Twoje zadanie:
    1. Oceń, jak dobrze użytkownik poradził sobie z przypadkiem w kontekście kanonicznych odpowiedzi.
    2. Wypunktuj najmocniejsze i najsłabsze elementy podejścia użytkownika.
    3. Przygotuj jednozdaniowy werdykt i krótkie streszczenie (2-3 zdania) całości.

    Informacje o przypadku:
    - Nazwa: {case_name}
    - Opis: {case_content}
    - Wstępna diagnoza referencyjna: {prelim_dx}

    Kanoniczne odpowiedzi instruktora (JSON):
    {canonical_answers}

    Historia etapów wraz z ostatnimi odpowiedziami (JSON):
    {stage_payload}

    Pełny transkrypt rozmowy (podzielony na etapy):
    {transcript}

    Zwróć wynik w czystym formacie JSON (UTF-8, bez komentarzy) dokładnie o strukturze:
    {{
      "score": <liczba całkowita 0-100 opisująca procentowe zaliczenie>,
      "verdict": "krótki werdykt po polsku",
      "summary": "2-3 zdania streszczające mocne i słabe strony po polsku",
      "positives": ["lista", "najważniejszych", "mocnych stron"],
      "negatives": ["lista", "obszarów", "do poprawy"]
    }}

    Jeśli nie jesteś w stanie dokonać oceny, zwróć JSON z wartością null dla wszystkich pól.
    """
)


def generate_summary_assessment(case: Case, chats):
    """Generuje ocenę i podsumowanie etapu na podstawie całej rozmowy."""

    stage_payload = _build_stage_payload(chats)
    transcript = _build_transcript(stage_payload) or "Brak historii rozmowy."

    canonical_answers_payload = {
        "diagnostics": case.diagnostics_norm or "",
        "first_exam": case.prelim_dx_raw or "",
        "meds": case.meds_norm or "",
        "reco": case.reco_norm or "",
        "dispo": case.dispo_norm or "",
    }

    instructions = SUMMARY_PROMPT_TEMPLATE.format(
        case_name=case.name,
        case_content=case.content or "Brak opisu.",
        prelim_dx=case.prelim_dx_raw or "Brak diagnozy referencyjnej.",
        canonical_answers=json.dumps(canonical_answers_payload, ensure_ascii=False, indent=2),
        stage_payload=json.dumps(stage_payload, ensure_ascii=False, indent=2),
        transcript=transcript,
    )

    try:
        raw_text = _call_openai_with_fallback(
            instructions=instructions,
            input_text=transcript,
            max_tokens=700,
        ).strip()
    except AuthenticationError:
        return {
            "error": "Błąd uwierzytelnienia z OpenAI. Sprawdź `OPENAI_API_KEY` i dostęp do modelu.",
            "raw": "",
        }
    except OpenAIError as e:
        logger.exception("Błąd OpenAI podczas generowania podsumowania: %s", e)
        return {
            "error": "Błąd usługi OpenAI. Spróbuj ponownie później.",
            "raw": "",
        }
    except RuntimeError as e:
        return {
            "error": f"Konfiguracja: {e}",
            "raw": "",
        }
    except Exception as exc:  # pragma: no cover - zależne od zewnętrznego API
        logger.exception("Nieoczekiwany błąd podczas generowania podsumowania: %s", exc)
        return {
            "error": "Wewnętrzny błąd podczas generowania podsumowania.",
            "raw": "",
        }

    data = _extract_json_payload(raw_text)
    if not data:
        return {
            "error": "Nie udało się zinterpretować odpowiedzi modelu.",
            "raw": raw_text,
        }

    return {
        "data": data,
        "raw": raw_text,
    }
