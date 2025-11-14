import json
from django.contrib.auth.models import User, AnonymousUser
from django.test import TestCase, RequestFactory
from django.contrib.sessions.middleware import SessionMiddleware
from django.http import Http404
from unittest.mock import patch

from .models import Case, Instruction, CaseHistory
from .services import render_instruction_body, resolve_instruction
from .views import auth_views, chat_views, history_views, utils


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





# --- helper do sesji dla RequestFactory ---


def _add_session(request):
    middleware = SessionMiddleware(lambda r: None)
    middleware.process_request(request)
    request.session.save()


# ===========================
#  AUTH VIEWS
# ===========================


class AuthViewsTests(TestCase):
    def setUp(self) -> None:
        self.factory = RequestFactory()

    def test_register_get_returns_200(self) -> None:
        request = self.factory.get("/register/")
        response = auth_views.register_view(request)

        self.assertEqual(response.status_code, 200)

    def test_register_post_invalid_shows_form_again(self) -> None:
        # Za mało danych, formularz będzie nieprawidłowy
        request = self.factory.post("/register/", data={"username": "user"})
        _add_session(request)
        request.user = AnonymousUser()

        response = auth_views.register_view(request)

        self.assertEqual(response.status_code, 200)  # brak redirectu, formularz z błędami

    def test_register_post_valid_creates_user_and_redirects(self) -> None:
        data = {
            "username": "newuser",
            "password1": "ComplexPass123",
            "password2": "ComplexPass123",
        }
        request = self.factory.post("/register/", data=data)
        _add_session(request)
        request.user = AnonymousUser()

        response = auth_views.register_view(request)

        self.assertEqual(response.status_code, 302)
        self.assertTrue(User.objects.filter(username="newuser").exists())

    def test_logout_view_redirects_to_home(self) -> None:
        request = self.factory.post("/logout/")
        _add_session(request)
        request.user = AnonymousUser()

        response = auth_views.logout_view(request)

        self.assertEqual(response.status_code, 302)


# ===========================
#  STAGE VIEW (chat_views)
# ===========================


class StageViewTests(TestCase):
    def setUp(self) -> None:
        self.factory = RequestFactory()
        self.case = Case.objects.create(name="Test case")
        self.user = User.objects.create_user(username="tester", password="test12345")

    def _make_request(self, method="GET", path="/", data=None, user=None):
        if method == "GET":
            request = self.factory.get(path, data=data or {})
        else:
            request = self.factory.post(path, data=data or {})
        _add_session(request)
        request.user = user or AnonymousUser()
        return request

    def test_unknown_stage_raises_404(self) -> None:
        request = self._make_request("GET")
        with self.assertRaises(Http404):
            chat_views.stage_view(request, case_slug=self.case.slug, stage="unknown")

    def test_get_stage_initializes_session_and_returns_200(self) -> None:
        request = self._make_request("GET")
        response = chat_views.stage_view(request, case_slug=self.case.slug, stage="diagnostics")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(request.session["active_case_slug"], self.case.slug)
        self.assertEqual(request.session.get("chats"), {})
        self.assertEqual(request.session.get("completed_stages"), [])

    @patch("chat.views.chat_views._bot_reply_stage_db", return_value="zaliczam etap")
    def test_post_non_ajax_updates_chat_and_marks_stage_completed(self, mock_bot) -> None:
        request = self._make_request(
            "POST",
            data={"message": "pacjent ma objawy"}
        )

        response = chat_views.stage_view(request, case_slug=self.case.slug, stage="diagnostics")

        # powinien być redirect na ten sam etap
        self.assertEqual(response.status_code, 302)
        chats = request.session["chats"]["diagnostics"]
        self.assertEqual(len(chats), 2)
        self.assertEqual(chats[0]["role"], "user")
        self.assertEqual(chats[1]["role"], "assistant")
        self.assertIn("zaliczam", chats[1]["text"].lower())
        self.assertIn("diagnostics", request.session["completed_stages"])
        self.assertTrue(request.session["can_proceed_to_dx"])

    def test_post_ajax_when_stage_already_completed_returns_error_json(self) -> None:
        # ustawiamy w sesji ukończony etap
        request = self._make_request(
            "POST",
            data={"message": "kolejne pytanie"}
        )
        request.session["active_case_slug"] = self.case.slug
        request.session["chats"] = {"diagnostics": []}
        request.session["completed_stages"] = ["diagnostics"]
        request.session.modified = True
        # symulujemy AJAX
        request.headers = {"x-requested-with": "XMLHttpRequest"}

        response = chat_views.stage_view(request, case_slug=self.case.slug, stage="diagnostics")

        self.assertEqual(response.status_code, 200)
        self.assertJSONEqual(
            response.content.decode(),
            {"ok": False, "error": "stage_completed"},
        )

    @patch("chat.views.chat_views.generate_summary_assessment")
    def test_summary_stage_saves_casehistory_for_authenticated_user(self, mock_summary) -> None:
        # przygotuj komplet etapów poza summary
        completed_core = [s for s in utils.STAGE_ORDER if s != "summary"]
        request = self._make_request("GET", user=self.user)
        request.session["active_case_slug"] = self.case.slug
        request.session["chats"] = {}
        request.session["completed_stages"] = completed_core
        request.session["case_saved"] = False
        request.session.modified = True

        mock_summary.return_value = {
            "data": {
                "score": 80,
                "verdict": "OK",
                "summary": "Testowe podsumowanie",
            },
            "raw": "{}",
        }

        response = chat_views.stage_view(request, case_slug=self.case.slug, stage="summary")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(request.session["case_saved"])
        self.assertEqual(
            CaseHistory.objects.filter(user=self.user, case=self.case).count(), 1
        )


# ===========================
#  HISTORY VIEWS
# ===========================


class HistoryViewsTests(TestCase):
    def setUp(self) -> None:
        self.factory = RequestFactory()
        self.user = User.objects.create_user(username="tester", password="test12345")
        self.case = Case.objects.create(name="History case")
        self.history = CaseHistory.objects.create(
            user=self.user,
            case=self.case,
            chats={"__summary__": {"verdict": "OK"}},
            completed_stages=["diagnostics"],
            is_completed=True,
        )

    def _make_request(self, method="GET", path="/", data=None, user=None):
        if method == "GET":
            request = self.factory.get(path, data=data or {})
        else:
            request = self.factory.post(path, data=data or {})
        _add_session(request)
        request.user = user or AnonymousUser()
        return request

    def test_history_list_requires_login_and_returns_200_for_authenticated(self) -> None:
        # zalogowany
        req_auth = self._make_request(user=self.user)
        resp_auth = history_views.history_list_view(req_auth)
        self.assertEqual(resp_auth.status_code, 200)

        # anonim → powinien być redirect (login_required)
        req_anon = self._make_request(user=AnonymousUser())
        resp_anon = history_views.history_list_view(req_anon)
        self.assertEqual(resp_anon.status_code, 302)

    def test_reset_case_view_clears_session_and_redirects(self) -> None:
        request = self._make_request(
            method="POST",
            data={},
            user=self.user,
        )
        # wstępny stan sesji
        request.session["active_case_slug"] = "other"
        request.session["chats"] = {"diagnostics": [{"role": "user", "text": "x"}]}
        request.session.modified = True

        response = history_views.reset_case_view(request, case_slug=self.case.slug)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(request.session["active_case_slug"], self.case.slug)
        self.assertEqual(request.session["chats"], {})
        self.assertEqual(request.session["completed_stages"], [])
        self.assertFalse(request.session["can_proceed_to_dx"])
        self.assertFalse(request.session["case_saved"])

    def test_completed_grouped_view_returns_200(self) -> None:
        request = self._make_request(user=self.user)
        response = history_views.completed_grouped(request)
        self.assertEqual(response.status_code, 200)

    def test_completed_case_view_returns_200(self) -> None:
        request = self._make_request(user=self.user)
        response = history_views.completed_case(request, case_slug=self.case.slug)
        self.assertEqual(response.status_code, 200)

    def test_completed_detail_view_returns_200(self) -> None:
        request = self._make_request(user=self.user)
        response = history_views.completed_detail(request, pk=self.history.pk)
        self.assertEqual(response.status_code, 200)


# ===========================
#  UTILS / SUMMARY
# ===========================


class UtilsTests(TestCase):
    def test_strip_accents_handles_none_and_polish(self) -> None:
        self.assertEqual(utils._strip_accents(None), "")

        result = utils._strip_accents("zażółć gęślą jaźń")

        self.assertEqual(result, "zazołc gesla jazn")


        for ch in "żóąęźćń":
            self.assertNotIn(ch, result)



    def test_check_can_proceed_matches_targets_case_insensitive(self) -> None:
        self.assertFalse(utils._check_can_proceed("", ["zaliczam"]))
        self.assertTrue(
            utils._check_can_proceed("Pacjent – ZALICZAM etap.", ["zaliczam"])
        )

    @patch("chat.views.utils._call_openai_with_fallback")
    def test_generate_summary_assessment_success(self, mock_call) -> None:
        case = Case.objects.create(
            name="Case",
            content="Opis przypadku",
            prelim_dx_raw="DX",
            meds_norm="Leczenie",
            diagnostics_norm="Diag",
            reco_norm="Zalecenia",
            dispo_norm="Dispo",
        )
        chats = {
            "diagnostics": [
                {"role": "user", "text": "pytanie"},
                {"role": "assistant", "text": "odpowiedź"},
            ]
        }

        mock_call.return_value = json.dumps(
            {
                "score": 90,
                "verdict": "Dobry wynik",
                "summary": "Krótki opis",
                "positives": [],
                "negatives": [],
            },
            ensure_ascii=False,
        )

        result = utils.generate_summary_assessment(case, chats)

        self.assertIn("data", result)
        self.assertEqual(result["data"]["score"], 90)
