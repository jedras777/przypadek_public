
from typing import Optional
from .models import Case, Instruction

def resolve_instruction(stage: str, case: Case) -> Optional[Instruction]:
    inst = (Instruction.objects
            .filter(case=case, stage=stage, active=True)
            .order_by("-version", "-updated_at")
            .first())
    if inst:
        return inst
    return (Instruction.objects
            .filter(case__isnull=True, stage=stage, active=True)
            .order_by("-version", "-updated_at")
            .first())

def case_norm_for_stage(case: Case, stage: str) -> str:
    return {
        "diagnostics": case.diagnostics_norm or "",
        "meds": case.meds_norm or "",
        "reco": case.reco_norm or "",
        "dispo": case.dispo_norm or "",
    }.get(stage, "")

def render_instruction_body(inst: Instruction, case: Case, *, user_answers, bot_answers, actual_msg: str) -> str:
    user_hist = "\n".join(user_answers) if isinstance(user_answers, (list, tuple)) else str(user_answers or "")
    bot_hist = "\n".join(bot_answers) if isinstance(bot_answers, (list, tuple)) else str(bot_answers or "")
    case_norm = case_norm_for_stage(case, inst.stage)
    prelim_dx = case.prelim_dx_raw or ""  # <<< kluczowe

    return inst.body.format(
        case_norm=case_norm,
        prelim_dx=prelim_dx,
        user_answers=user_hist,
        bot_answers=bot_hist,
        actual_msg=actual_msg,
    )
