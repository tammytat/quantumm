"""Test suite for the Quantum TechHub learning platform.

Focus areas (highest risk first):
* Code-execution endpoints require authentication (no anonymous RCE).
* XP is awarded exactly once per lesson (anti-farming).
* ``check_code`` returns the right verdicts without a live Docker sandbox.
* Lesson access is gated on enrollment.
* Payment verification checks amount + email and is idempotent.
"""
from decimal import Decimal
import json
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse

from .models import (
    Course,
    Lesson,
    LessonBlock,
    LessonCompletion,
    Module,
    Payment,
    Profile,
    TeacherProfile,
)
from .views import _award_lesson_xp, _is_csv_load_assignment

# Use a dedicated locmem cache so the real rate limiter never leaks state
# between tests and never touches the application cache.
TEST_CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "test-ratelimit",
    }
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_teacher(username="teacher"):
    user = User.objects.create_user(username=username, password="pw", email=f"{username}@example.com")
    TeacherProfile.objects.create(user=user, is_approved=True, paystack_subaccount_code="ACCT_test")
    return user


def make_course(author, slug="python-101", price="1000.00"):
    return Course.objects.create(
        title="Python 101",
        description="Intro course",
        slug=slug,
        price=Decimal(price),
        author=author,
    )


def make_lesson(course, title="Lesson 1"):
    module = Module.objects.create(course=course, title="Module 1", order=1)
    return Lesson.objects.create(module=module, title=title, order=1)


# ---------------------------------------------------------------------------
# Pure-function unit tests
# ---------------------------------------------------------------------------

class CsvLoadAssignmentTests(TestCase):
    def test_detects_pandas_read_csv_assignment(self):
        self.assertTrue(_is_csv_load_assignment("import pandas as pd\ndf = pd.read_csv('data.csv')"))
        self.assertTrue(_is_csv_load_assignment("df = pd.read_csv('Downloads\\\\data.csv')"))

    def test_rejects_unrelated_code(self):
        self.assertFalse(_is_csv_load_assignment("print('hello')"))
        self.assertFalse(_is_csv_load_assignment("x = pd.read_excel('data.xlsx')"))
        self.assertFalse(_is_csv_load_assignment("df = something_else('data.csv')"))
        # Syntax errors must not raise.
        self.assertFalse(_is_csv_load_assignment("def broken(:"))


class AwardXpTests(TestCase):
    def setUp(self):
        self.teacher = make_teacher()
        self.course = make_course(self.teacher)
        self.lesson = make_lesson(self.course)
        self.student = User.objects.create_user(username="student", password="pw")

    def test_xp_awarded_once(self):
        completion, awarded = _award_lesson_xp(self.student, self.lesson, points=20)
        self.assertTrue(awarded)
        self.assertEqual(Profile.objects.get(user=self.student).points, 20)

        # Second call must not grant points again.
        completion, awarded = _award_lesson_xp(self.student, self.lesson, points=20)
        self.assertFalse(awarded)
        self.assertEqual(Profile.objects.get(user=self.student).points, 20)
        self.assertEqual(LessonCompletion.objects.filter(user=self.student, lesson=self.lesson).count(), 1)


# ---------------------------------------------------------------------------
# Access control
# ---------------------------------------------------------------------------

class LessonAccessTests(TestCase):
    def setUp(self):
        self.teacher = make_teacher()
        self.course = make_course(self.teacher)
        self.lesson = make_lesson(self.course)
        self.url = reverse("lesson_detail", kwargs={"slug": self.course.slug, "lesson_id": self.lesson.id})

    def test_anonymous_redirected_to_login(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login/", response.url)

    def test_non_enrolled_user_redirected_to_checkout(self):
        User.objects.create_user(username="outsider", password="pw")
        self.client.login(username="outsider", password="pw")
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertIn("checkout", response.url)

    def test_enrolled_user_can_open_lesson(self):
        student = User.objects.create_user(username="enrolled", password="pw")
        self.course.students.add(student)
        self.client.login(username="enrolled", password="pw")
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)


class CodeExecutionAuthTests(TestCase):
    """The former anonymous-RCE endpoints must now require a login."""

    def test_validate_code_requires_login(self):
        response = self.client.post(
            reverse("validate_code"),
            data='{"code": "print(1)"}',
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login/", response.url)

    def test_execute_environment_requires_login(self):
        response = self.client.post(
            reverse("execute_environment"),
            data='{"env_key": "python", "payload": "print(1)"}',
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 302)

    def test_validate_code_rejects_non_post(self):
        User.objects.create_user(username="u", password="pw")
        self.client.login(username="u", password="pw")
        response = self.client.get(reverse("validate_code"))
        self.assertEqual(response.status_code, 405)


# ---------------------------------------------------------------------------
# check_code verdicts (sandbox mocked out)
# ---------------------------------------------------------------------------

@override_settings(CACHES=TEST_CACHES)
class CheckCodeTests(TestCase):
    def setUp(self):
        self.teacher = make_teacher()
        self.course = make_course(self.teacher)
        self.lesson = make_lesson(self.course)
        self.block = LessonBlock.objects.create(
            lesson=self.lesson,
            block_type="challenge",
            order=1,
            expected_output="42",
        )
        self.student = User.objects.create_user(username="student", password="pw")
        self.course.students.add(self.student)
        self.client.login(username="student", password="pw")
        self.url = reverse("check_code", kwargs={"lesson_id": self.lesson.id})

    def _post(self, code):
        return self.client.post(
            self.url,
            data=json.dumps({"code": code, "block_id": self.block.id}),
            content_type="application/json",
        )

    @patch("accounts.views.EnvironmentManager.execute")
    def test_correct_output_marks_correct_and_awards_xp(self, mock_execute):
        mock_execute.return_value = {"status": "success", "output": "42"}
        response = self._post("print(42)")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "correct")
        self.assertEqual(Profile.objects.get(user=self.student).points, 20)

    @patch("accounts.views.EnvironmentManager.execute")
    def test_wrong_output_marks_incorrect(self, mock_execute):
        mock_execute.return_value = {"status": "success", "output": "rect(1)"}
        response = self._post("print(43)")
        self.assertEqual(response.json()["status"], "incorrect")
        self.assertEqual(Profile.objects.get(user=self.student).points, 0)


# ---------------------------------------------------------------------------
# Payment verification
# ---------------------------------------------------------------------------

@override_settings(CACHES=TEST_CACHES)
class PaymentSuccessTests(TestCase):
    def setUp(self):
        self.teacher = make_teacher()
        self.course = make_course(self.teacher, price="1000.00")
        self.student = User.objects.create_user(username="buyer", password="pw", email="buyer@example.com")
        self.client.login(username="buyer", password="pw")
        self.url = reverse("payment_success", kwargs={"slug": self.course.slug})

    def _verify_response(self, amount=100000, email="buyer@example.com", status="success"):
        return {
            "status": True,
            "data": {
                "status": status,
                "amount": amount,
                "customer": {"email": email},
            },
        }

    @patch("accounts.views.requests.get")
    def test_valid_payment_enrolls_and_records(self, mock_get):
        mock_get.return_value.json.return_value = self._verify_response()
        mock_get.return_value.status_code = 200
        response = self.client.get(self.url, {"reference": "QTH-123"})
        self.assertEqual(response.status_code, 200)
        self.assertIn(self.student, self.course.students.all())
        self.assertTrue(Payment.objects.filter(reference="QTH-123", verified=True).exists())

    @patch("accounts.views.requests.get")
    def test_wrong_amount_does_not_enroll(self, mock_get):
        mock_get.return_value.json.return_value = self._verify_response(amount=5)
        mock_get.return_value.status_code = 200
        self.client.get(self.url, {"reference": "QTH-BAD"})
        self.assertNotIn(self.student, self.course.students.all())
        self.assertFalse(Payment.objects.filter(reference="QTH-BAD").exists())

    @patch("accounts.views.requests.get")
    def test_payment_is_idempotent(self, mock_get):
        mock_get.return_value.json.return_value = self._verify_response()
        mock_get.return_value.status_code = 200
        self.client.get(self.url, {"reference": "QTH-777"})
        self.client.get(self.url, {"reference": "QTH-777"})
        self.assertEqual(Payment.objects.filter(reference="QTH-777").count(), 1)

    @patch("accounts.views.requests.get")
    def test_email_mismatch_is_rejected(self, mock_get):
        mock_get.return_value.json.return_value = self._verify_response(email="someone@else.com")
        mock_get.return_value.status_code = 200
        self.client.get(self.url, {"reference": "QTH-EMAIL"})
        self.assertNotIn(self.student, self.course.students.all())


# ---------------------------------------------------------------------------
# Auth flow
# ---------------------------------------------------------------------------

class SignupLoginTests(TestCase):
    def test_signup_creates_user_and_profile(self):
        response = self.client.post(
            reverse("signup"),
            {"username": "newbie", "email": "new@example.com", "password": "S3cret!pass", "password_confirm": "S3cret!pass"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(User.objects.filter(username="newbie").exists())
        self.assertTrue(Profile.objects.filter(user__username="newbie").exists())

    def test_duplicate_username_rejected(self):
        User.objects.create_user(username="dup", password="pw", email="dup@example.com")
        self.client.post(
            reverse("signup"),
            {"username": "dup", "email": "other@example.com", "password": "pw", "password_confirm": "pw"},
        )
        self.assertEqual(User.objects.filter(username="dup").count(), 1)
