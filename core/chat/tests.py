from django.test import TestCase

from .models import Case, Instruction
from .services import render_instruction_body, resolve_instruction


class CaseModelTests(TestCase):
    def test_slug_is_generated_from_name(self) -> None:
        case = Case.objects.create(name="Pacjent z bólem w klatce piersiowej")

        self.assertEqual(case.slug, "pacjent-z-bolem-w-klatce-piersiowej")


class ResolveInstructionTests(TestCase):
    def setUp(self) -> None:
        self.case = Case.objects.create(name="Test case")
        self.global_instruction = Instruction.objects.create(
            stage="diagnostics",
            body="Diagnozuj: {case_norm}",
            active=True,
        )

    def test_returns_case_specific_instruction_when_available(self) -> None:
        specific = Instruction.objects.create(
            case=self.case,
            stage="diagnostics",
            body="Szczególna instrukcja",
            active=True,
            version=2,
        )

        result = resolve_instruction("diagnostics", self.case)

        self.assertEqual(result, specific)

    def test_falls_back_to_global_instruction(self) -> None:
        result = resolve_instruction("diagnostics", self.case)

        self.assertEqual(result, self.global_instruction)


class RenderInstructionBodyTests(TestCase):
    def setUp(self) -> None:
        self.case = Case.objects.create(
            name="Case", meds_norm="Podaj ASA", prelim_dx_raw="STEMI"
        )
        self.instruction = Instruction.objects.create(
            case=self.case,
            stage="meds",
            body=(
                "{case_norm}\n{prelim_dx}\nU: {user_answers}\nB: {bot_answers}\nMSG: {actual_msg}"
            ),
        )

    def test_interpolates_all_known_placeholders(self) -> None:
        rendered = render_instruction_body(
            self.instruction,
            self.case,
            user_answers=["pacjent zgłasza ból", "ból promieniuje"],
            bot_answers=["podaj ASA"],
            actual_msg="nowe dane",
        )

        self.assertIn("Podaj ASA", rendered)
        self.assertIn("STEMI", rendered)
        self.assertIn("pacjent zgłasza ból\nból promieniuje", rendered)
        self.assertIn("podaj ASA", rendered)
        self.assertTrue(rendered.endswith("MSG: nowe dane"))