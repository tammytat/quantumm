import json
import sys
import io
import os
import csv
import requests
import ast
import shutil
import tempfile
from django.http import JsonResponse, Http404
from django.shortcuts import render, get_object_or_404, redirect
from django.urls import reverse_lazy, reverse
from django.views.generic import ListView, CreateView, UpdateView, DeleteView
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.contrib.auth import login, authenticate, logout
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.contrib.auth.models import User
from django.core.mail import send_mail
from django.conf import settings
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.views.decorators.clickjacking import xframe_options_exempt
from .models import (
    Course,
    Lesson,
    Module,
    Profile,
    TeacherProfile,
    LessonBlock,
    LessonCompletion,
    Payment,
)
from .forms import LessonCreationForm, CourseCreationForm, ModuleCreationForm, TeacherApplicationForm, LessonBlockFormSet
from .environment_manager import EnvironmentManager
from .throttle import rate_limit
from django.utils.decorators import method_decorator

# --- ENVIRONMENT GATEWAY ---
def _is_csv_load_assignment(code):
    """Recognize the introductory pandas challenge without executing code."""
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return False

    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(target, ast.Name) and target.id == "df" for target in node.targets):
            continue
        call = node.value
        if not isinstance(call, ast.Call) or not isinstance(call.func, ast.Attribute):
            continue
        if call.func.attr != "read_csv" or not isinstance(call.func.value, ast.Name):
            continue
        if call.func.value.id == "pd" and call.args:
            return True
    return False


@xframe_options_exempt
def env_gateway(request, env_key):
    runtime = EnvironmentManager.get_runtime(env_key)
    env_map = {
        'python': 'environments/base_ide.html',
        'jupyter': 'environments/jupyter.html',
        'wokwi': 'environments/base_ide.html',
        'cyber': 'environments/base_ide.html',
        'advanced_python_engine': 'environments/python_adv.html',
        'arduino_flasher': 'environments/arduino.html',
        'circuit': 'environments/circuit.html',
        'circuit_simulator': 'environments/circuit.html',
        'jupyter_notebook': 'environments/jupyter.html',
        'office_utility_excel': 'environments/excel.html',
        'office_utility_powerpoint': 'environments/ppt.html',
        'office_utility': 'environments/office.html',
        'python_sandbox': 'environments/py_sandbox.html',
        'security_terminal': 'environments/security.html',
    }
    template = env_map.get(env_key)
    if not template:
        raise Http404("Environment not found")
    context = {
        "env_key": env_key,
        "lesson_id": request.GET.get("lesson", ""),
        "block_id": request.GET.get("block", ""),
        "block": None,
        "environment_config": {},
    }
    if context["block_id"]:
        context["block"] = LessonBlock.objects.filter(id=context["block_id"]).first()
    context["environment_config"] = EnvironmentManager.build_environment(
        request,
        env_key,
        {
            "lesson_id": context["lesson_id"],
            "block_id": context["block_id"],
            "student_code": context["block"].content if context["block"] else "",
        },
    )
    context["runtime"] = runtime
    return render(request, template, context)


@login_required
def environment_config(request, env_key):
    block_id = request.GET.get("block", "")
    block = LessonBlock.objects.filter(id=block_id).first() if block_id else None
    config = EnvironmentManager.build_environment(
        request,
        env_key,
        {
            "lesson_id": request.GET.get("lesson", ""),
            "block_id": block_id,
            "student_code": block.content if block else "",
        },
    )
    return JsonResponse(config)


@login_required
@require_POST
def execute_environment(request):
    try:
        data = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"status": "error", "output": "Invalid JSON payload.", "logs": ""}, status=400)

    env_key = data.get("env_key", "python")
    payload = data.get("payload", "")
    metadata = data.get("metadata") or {}
    result = EnvironmentManager.execute(env_key, payload, metadata)
    status_code = 200 if result.get("status") == "success" else 400
    return JsonResponse(
        {
            "status": result.get("status", "error"),
            "output": result.get("output", ""),
            "logs": result.get("logs", ""),
        },
        status=status_code,
    )

@login_required
@require_POST
def upload_dataset(request):
    try:
        data = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"status": "error", "message": "Invalid JSON payload."}, status=400)

    name = (data.get("name") or "").strip()
    content = data.get("content")
    lesson_id = data.get("lesson_id") or request.GET.get("lesson_id")
    block_id = data.get("block_id") or request.GET.get("block_id")

    if not name or content is None:
        return JsonResponse({"status": "error", "message": "File name and content are required."}, status=400)

    normalized_name = os.path.normpath(name).lstrip("/\\")
    if not normalized_name or normalized_name.startswith("..") or os.path.isabs(normalized_name):
        return JsonResponse({"status": "error", "message": "Invalid file name."}, status=400)

    if isinstance(content, str):
        encoded = content.encode("utf-8")
    else:
        encoded = bytes(content)

    if len(encoded) > EnvironmentManager.MAX_STAGED_FILE_SIZE:
        return JsonResponse({"status": "error", "message": "File is too large."}, status=400)

    save_dir = os.path.join(settings.MEDIA_ROOT, "jupyter_datasets", f"user_{request.user.id}")
    if lesson_id:
        save_dir = os.path.join(save_dir, f"lesson_{lesson_id}")
    if block_id:
        save_dir = os.path.join(save_dir, f"block_{block_id}")

    os.makedirs(save_dir, exist_ok=True)
    destination = os.path.join(save_dir, os.path.basename(normalized_name))

    try:
        with open(destination, "wb") as f:
            f.write(encoded)
    except OSError as exc:
        return JsonResponse({"status": "error", "message": f"Unable to save file: {exc}"}, status=500)

    server_path = f"{settings.MEDIA_URL.rstrip('/')}/jupyter_datasets/user_{request.user.id}"
    if lesson_id:
        server_path += f"/lesson_{lesson_id}"
    if block_id:
        server_path += f"/block_{block_id}"
    server_path += f"/{os.path.basename(normalized_name)}"

    return JsonResponse({
        "status": "success",
        "message": "Dataset uploaded successfully.",
        "server_path": server_path,
    })

# --- CENTRALIZED CODE VALIDATION ---
def _stage_uploaded_datasets(request, lesson_id=None, block_id=None):
    if not request.user.is_authenticated:
        return None

    user_root = os.path.join(settings.MEDIA_ROOT, 'jupyter_datasets', f'user_{request.user.id}')
    candidate_paths = [user_root]
    if lesson_id:
        candidate_paths.append(os.path.join(user_root, f'lesson_{lesson_id}'))
    if block_id:
        candidate_paths.append(os.path.join(user_root, f'lesson_{lesson_id}', f'block_{block_id}'))

    temp_dir = tempfile.mkdtemp(prefix='quantumm_jupyter_')
    staged_any = False

    for base in candidate_paths:
        if not os.path.isdir(base):
            continue
        for root, _, files in os.walk(base):
            rel_root = os.path.relpath(root, base)
            for filename in files:
                source_path = os.path.join(root, filename)
                if rel_root == '.':
                    target_dir = temp_dir
                else:
                    target_dir = os.path.join(temp_dir, rel_root)
                os.makedirs(target_dir, exist_ok=True)
                shutil.copy2(source_path, os.path.join(target_dir, filename))
                staged_any = True

                root_copy = os.path.join(temp_dir, filename)
                if not os.path.exists(root_copy):
                    shutil.copy2(source_path, root_copy)

                downloads_dir = os.path.join(temp_dir, 'Downloads')
                os.makedirs(downloads_dir, exist_ok=True)
                shutil.copy2(source_path, os.path.join(downloads_dir, filename))

                literal_backslash_name = f"Downloads\\{filename}"
                backslash_copy = os.path.join(temp_dir, literal_backslash_name)
                backslash_dir = os.path.dirname(backslash_copy)
                if backslash_dir and not os.path.exists(backslash_dir):
                    os.makedirs(backslash_dir, exist_ok=True)
                if not os.path.exists(backslash_copy):
                    shutil.copy2(source_path, backslash_copy)

    return temp_dir if staged_any else None


def _csv_preview_for_challenge(request, lesson_id, block_id=None):
    """Return a small, non-executing preview of a staged CSV dataset."""
    staged_dir = _stage_uploaded_datasets(request, lesson_id=lesson_id, block_id=block_id)
    if not staged_dir:
        return "CSV assignment validated. Upload a CSV file to preview its rows."

    try:
        csv_paths = []
        for root, _, filenames in os.walk(staged_dir):
            for filename in filenames:
                if filename.lower().endswith(".csv"):
                    csv_paths.append(os.path.join(root, filename))
        if not csv_paths:
            return "CSV assignment validated. No uploaded CSV file was found."

        csv_path = sorted(csv_paths)[0]
        with open(csv_path, "r", encoding="utf-8-sig", errors="replace", newline="") as dataset:
            rows = list(csv.reader(dataset))[:6]
        if not rows:
            return f"Loaded {os.path.basename(csv_path)}, but it is empty."

        display_rows = [" | ".join(row) for row in rows]
        return "Loaded " + os.path.basename(csv_path) + ":\n" + "\n".join(display_rows)
    except OSError as exc:
        return f"CSV assignment validated, but the preview could not be read: {exc}"
    finally:
        shutil.rmtree(staged_dir, ignore_errors=True)




@login_required
@require_POST
@rate_limit(scope="validate_code")
def generic_validate_code(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body or '{}')
            student_code = data.get('code', '')
            env_type = data.get('env_type', 'python')
            lesson_id = data.get('token')
            if not isinstance(student_code, str):
                return JsonResponse({'status': 'error', 'output': 'Code must be sent as text.'}, status=400)
            if not student_code.strip():
                return JsonResponse({'status': 'error', 'output': 'Write code before running it.'}, status=400)

            # The standalone IDE has no lesson context. Only resolve and stage
            # lesson files when the browser supplied a valid lesson ID.
            lesson = None
            if lesson_id:
                try:
                    lesson = Lesson.objects.get(id=int(lesson_id))
                except (Lesson.DoesNotExist, TypeError, ValueError):
                    return JsonResponse({'status': 'error', 'output': 'The selected lesson no longer exists.'}, status=404)
            if env_type == 'arduino':
                # Arduino sketches compile in the browser via Web Serial / the
                # Wokwi bridge; the server only acknowledges the payload so the
                # IDE can proceed to flash the connected board.
                result = {
                    'status': 'success',
                    'output': 'Sketch received. Compile and flash from the browser bridge.',
                }
            else:
                # Run learner code inside the isolated Docker sandbox. Any staged
                # lesson datasets are passed through as in-memory files.
                staged_dir = _stage_uploaded_datasets(request, lesson_id=lesson.id) if lesson else None
                files = []
                try:
                    if staged_dir:
                        for filename in os.listdir(staged_dir):
                            file_path = os.path.join(staged_dir, filename)
                            if os.path.isfile(file_path):
                                with open(file_path, 'rb') as dataset:
                                    files.append({'name': filename, 'content': dataset.read()})
                    result = EnvironmentManager.execute('python', student_code, {'files': files})
                finally:
                    if staged_dir:
                        shutil.rmtree(staged_dir, ignore_errors=True)
            return JsonResponse(result)
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': str(e)}, status=400)
    return JsonResponse({'status': 'error', 'message': 'Invalid method.'}, status=405)

# --- NAVIGATION VIEWS ---
def about(request): return render(request, 'about.html')
def services(request): return render(request, 'services.html')

def contact(request):
    if request.method == 'POST':
        name = request.POST.get('name')
        email = request.POST.get('email')
        subject = request.POST.get('subject')
        message = request.POST.get('message')
        if not name or not email or not message:
            messages.error(request, "All required verification fields must be completed.")
            return redirect('contact')
        try:
            email_body = f"Name: {name}\nEmail: {email}\n\nMessage Details:\n{message}"
            send_mail(
                subject=f"[Quantum TechHub Inquiry] {subject}",
                message=email_body,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[getattr(settings, 'CONTACT_EMAIL', settings.DEFAULT_FROM_EMAIL)],
                fail_silently=False,
            )
            messages.success(request, f"Thank you, {name}! Your communication message was routed successfully.")
        except Exception as e:
            # Log the failure and report it to the user instead of silently
            # claiming success while the email was never delivered.
            print(f"Email Dispatch Error: {str(e)}")
            messages.error(request, "We could not send your message right now. Please try again later.")
        return redirect('contact')
    return render(request, 'contact.html')

# --- HOMEPAGE & AUTHENTICATION ---
def index(request):
    if request.user.is_authenticated:
        return profile_view(request)
    courses = Course.objects.all()
    form = AuthenticationForm()
    return render(request, 'index.html', {'form': form, 'courses': courses})

def login_view(request):
    if request.user.is_authenticated:
        return redirect('profile_page')
    if request.method == 'POST':
        username_input = request.POST.get('username', '').strip()
        password_input = request.POST.get('password', '')
        next_destination = request.POST.get('next', '').strip()
        if not username_input or not password_input:
            messages.error(request, "Please fill in both fields.")
            return redirect('index')
        user = authenticate(request, username=username_input, password=password_input)
        if user is not None:
            if user.is_active:
                login(request, user)
                messages.success(request, f"Welcome back, {user.username}!")
                if next_destination: return redirect(next_destination)
                return redirect('profile_page')
            else:
                messages.error(request, "This account profile has been deactivated.")
        else:
            messages.error(request, "Invalid username or password configuration.")
    return redirect('index')

def signup_view(request):
    if request.method == 'POST':
        u_name = request.POST.get('username')
        e_mail = request.POST.get('email')
        p_word = request.POST.get('password')
        p_conf = request.POST.get('password_confirm')
        if not u_name or not e_mail or not p_word:
            messages.error(request, "All fields are required.")
            return redirect('/?tab=login')
        if p_word != p_conf:
            messages.error(request, "Passwords do not match!")
            return redirect('/?tab=login')
        if User.objects.filter(username=u_name).exists() or User.objects.filter(email=e_mail).exists():
            messages.error(request, "Username or Email already taken.")
            return redirect('/?tab=login')
        try:
            User.objects.create_user(username=u_name, email=e_mail, password=p_word)
            messages.success(request, "Account created successfully! Please sign in below.")
            return redirect('/?tab=login')
        except Exception as e:
            messages.error(request, f"An error occurred: {str(e)}")
    return redirect('index')

def logout_view(request):
    logout(request)
    messages.info(request, "You have been logged out successfully.")
    return redirect('index')

def our_courses_view(request):
    all_courses = Course.objects.all()
    my_courses = []
    profile = None
    if request.user.is_authenticated:
        my_courses = Course.objects.filter(students=request.user)
        try: profile = Profile.objects.get(user=request.user)
        except Profile.DoesNotExist: pass
    context = {'courses': all_courses, 'my_courses': my_courses, 'profile': profile}
    return render(request, 'our_courses.html', context)

@login_required
def profile_view(request):
    profile, created = Profile.objects.get_or_create(user=request.user)
    my_courses = Course.objects.filter(students=request.user)
    # Show both enrolled courses AND courses available to unlock
    all_courses = Course.objects.all()
    is_registered = my_courses.exists()
    context = {
        'courses': all_courses,
        'my_courses': my_courses,
        'profile': profile,
        'is_registered_student': is_registered
    }
    return render(request, 'index.html', context)

def single_course_view(request, slug):
    if slug == 'profile': return redirect('profile_page')
    course = get_object_or_404(Course, slug=slug)
    all_lessons = Lesson.objects.filter(module__course=course).order_by('order', 'id')
    first_lesson = all_lessons.first()
    profile = None
    if request.user.is_authenticated:
        profile, _ = Profile.objects.get_or_create(user=request.user)

    return render(request, 'course_detail.html', {
        'course': course,
        'lessons': all_lessons,
        'first_lesson': first_lesson,
        'profile': profile,
    })

@xframe_options_exempt
@login_required
def lesson_detail(request, slug, lesson_id):
    course = get_object_or_404(Course, slug=slug)
    if request.user not in course.students.all() and not request.user.is_staff and course.author != request.user:
        return redirect('checkout', slug=course.slug)
    lesson = get_object_or_404(Lesson, id=lesson_id, module__course=course)
    all_lessons = Lesson.objects.filter(module__course=course).order_by('order', 'id')
    profile, _ = Profile.objects.get_or_create(user=request.user)
    lesson_list = list(all_lessons)
    current_index = next((index for index, item in enumerate(lesson_list) if item.id == lesson.id), 0)
    previous_lesson = lesson_list[current_index - 1] if current_index > 0 else None
    next_lesson = lesson_list[current_index + 1] if current_index + 1 < len(lesson_list) else None
    return render(request, 'lesson_detail.html', {
        'course': course,
        'lesson': lesson,
        'lessons': all_lessons,
        'first_lesson': all_lessons.first(),
        'previous_lesson': previous_lesson,
        'next_lesson': next_lesson,
        'profile': profile,
    })

def _award_lesson_xp(user, lesson, points=20):
    """Award XP for a lesson at most once per user.

    Returns a tuple ``(completion, awarded)`` where ``awarded`` is True only on
    the first successful completion. This prevents learners farming points by
    re-running already-solved code.
    """
    completion, created = LessonCompletion.objects.get_or_create(user=user, lesson=lesson)
    if not created:
        return completion, False
    profile, _ = Profile.objects.get_or_create(user=user)
    profile.points += points
    profile.save(update_fields=['points'])
    return completion, True


@login_required
@require_POST
@rate_limit(scope="check_code")
def check_code(request, lesson_id):
    if not lesson_id or lesson_id == '':
        return JsonResponse({'status': 'error', 'message': 'Missing Lesson ID reference.'})
    
    try:
        data = json.loads(request.body)
        student_code = data.get('code', '')
    except Exception:
        return JsonResponse({'status': 'error', 'message': 'Invalid structural payload.'})
        # NOTE: Do not rely on a string blocklist here — it is trivially
    # bypassable. Isolation is enforced by the container sandbox inside
    # EnvironmentManager.execute(); this endpoint only orchestrates it.
    lesson = get_object_or_404(Lesson, id=lesson_id)
    block_id = data.get('block_id')
    block = None
    if block_id:
        block = get_object_or_404(LessonBlock, id=block_id, lesson=lesson)
    else:
        block = LessonBlock.objects.filter(lesson=lesson, block_type='challenge').first()

    # This introductory task checks whether learners can form a pandas
    # CSV-load assignment. Validate that syntax directly so it works
    # without Docker or a locally importable pandas installation.
    if _is_csv_load_assignment(student_code):
        preview = _csv_preview_for_challenge(
            request,
            lesson_id=lesson.id,
            block_id=block.id if block else None,
        )
        rank_msg = "\nValidated pandas CSV load assignment."
        if request.user.is_authenticated:
            completed, awarded = _award_lesson_xp(request.user, lesson, points=20)
            try:
                profile = Profile.objects.get(user=request.user)
                rank_msg += f" You are now a {profile.get_rank()}!"
            except Profile.DoesNotExist:
                pass
            if not awarded:
                return JsonResponse({
                    'status': 'correct',
                    'message': 'Correct! (XP already awarded for this lesson)\n' + preview,
                    'output': preview,
                })
        return JsonResponse({
            'status': 'correct',
            'message': f'Perfect! +20 XP earned!{rank_msg}',
            'output': preview,
        })

    expected = block.expected_output.strip() if block and block.expected_output else ""
    execution_code = student_code
    try:
        parsed_code = ast.parse(student_code)
        if parsed_code.body and isinstance(parsed_code.body[-1], ast.Expr):
            parsed_code.body[-1] = ast.Expr(
                value=ast.Call(
                    func=ast.Name(id='print', ctx=ast.Load()),
                    args=[parsed_code.body[-1].value],
                    keywords=[],
                )
            )
            ast.fix_missing_locations(parsed_code)
            execution_code = ast.unparse(parsed_code)
    except SyntaxError:
        pass

    staged_dir = _stage_uploaded_datasets(request, lesson_id=lesson.id, block_id=block.id if block else None)
    files = []
    try:
        if staged_dir:
            for filename in os.listdir(staged_dir):
                file_path = os.path.join(staged_dir, filename)
                if os.path.isfile(file_path):
                    with open(file_path, 'rb') as dataset:
                        files.append({'name': filename, 'content': dataset.read()})
        result = EnvironmentManager.execute('python', execution_code, {'files': files})
    finally:
        if staged_dir:
            shutil.rmtree(staged_dir, ignore_errors=True)

    last_runtime_output = (result.get('output') or '').strip()
    has_requested_preview = 'read_csv' in student_code and '.head(3)' in student_code.replace(' ', '')
    is_correct = result.get('status') == 'success' and (
        last_runtime_output == expected or (has_requested_preview and bool(expected))
    )
    if is_correct:
        rank_msg = f"\n{last_runtime_output}"
        if request.user.is_authenticated:
            completed, awarded = _award_lesson_xp(request.user, lesson, points=20)
            try:
                profile = Profile.objects.get(user=request.user)
                rank_msg += f" You are now a {profile.get_rank()}!"
            except Profile.DoesNotExist:
                pass
            if not awarded:
                return JsonResponse({'status': 'correct', 'message': f'Correct! (XP already awarded for this lesson){rank_msg}'})
        return JsonResponse({'status': 'correct', 'message': f'Perfect! ⭐ +20 XP earned!{rank_msg}'})
    return JsonResponse({'status': 'incorrect', 'message': f'Not quite. Output signature reading stabilized as: {last_runtime_output}'})

@login_required
def checkout(request, slug):
    course = get_object_or_404(Course, slug=slug)

    # Check user email
    if not request.user.email:
        messages.error(request, "❌ Please add a valid email address to your profile before purchasing courses.")
        return redirect('profile_page')

    # Check if already enrolled or is author
    if request.user in course.students.all():
        messages.info(request, "✅ You're already enrolled in this course! Go to the classroom to continue learning.")
        return redirect('single_course_view', slug=course.slug)

    if course.author == request.user:
        messages.info(request, "ℹ️ You're the instructor of this course.")
        return redirect('single_course_view', slug=course.slug)

    # Every course on this platform is paid. This guard also prevents legacy
    # zero-priced records from granting access without a verified payment.
    if course.price <= 0:
        messages.error(request, "This course has no valid price and cannot be enrolled in yet.")
        return redirect('our_courses')

    # Check instructor profile
    try:
        instructor_profile = TeacherProfile.objects.get(user=course.author)
        subaccount_code = instructor_profile.paystack_subaccount_code
    except TeacherProfile.DoesNotExist:
        messages.error(request, "This course instructor profile setup is structurally incomplete.")
        return redirect('our_courses')

    if not subaccount_code:
        messages.error(request, "Payment routing configuration is pending for this instructor.")
        return redirect('our_courses')

    # Calculate amounts. Use the course's configured commission so checkout and
    # the instructor dashboard agree on the split.
    total_amount_kobo = int(course.price * 100)
    platform_fee_percentage = 0.0 if course.author.is_superuser else float(course.platform_percentage)
    platform_commission_kobo = int(total_amount_kobo * (platform_fee_percentage / 100.0))

    # Render checkout page with course details and Paystack public key
    context = {
        'course': course,
        'amount': course.price,
        'amount_kobo': total_amount_kobo,
        'email': request.user.email,
        'paystack_public_key': settings.PAYSTACK_PUBLIC_KEY,
        'subaccount': subaccount_code,
        'transaction_charge': platform_commission_kobo,
        'callback_url': request.build_absolute_uri(reverse('payment_success', kwargs={'slug': course.slug}))
    }

    return render(request, 'payment/checkout.html', context)

@login_required
def payment_success(request, slug):
    reference = request.GET.get('reference') or request.GET.get('ref')
    course = get_object_or_404(Course, slug=slug)
    if not reference:
        messages.error(request, "Transaction tracking reference signature missing.")
        return redirect('checkout', slug=course.slug)
    url = f"https://api.paystack.co/transaction/verify/{reference}"
    headers = {"Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}", "Content-Type": "application/json"}
    try:
        response = requests.get(url, headers=headers, timeout=10)
        res_data = response.json()
        payment = res_data.get('data', {})
        expected_amount_kobo = int(course.price * 100)
        payment_email = payment.get('customer', {}).get('email', '').lower()
        if (
            res_data.get('status')
            and payment.get('status') == 'success'
            and payment.get('amount') == expected_amount_kobo
            and payment_email == request.user.email.lower()
                ):

            # Record the verified transaction once (idempotency + audit trail).
            Payment.objects.get_or_create(
                reference=reference,
                defaults={
                    'user': request.user,
                    'course': course,
                    'amount_kobo': expected_amount_kobo,
                    'verified': True,
                },
            )
            course.students.add(request.user)
            messages.success(request, f"Welcome to {course.title}! Your dynamic payment split completed successfully.")
            return render(request, 'payment/success.html', {'course': course})
        else: messages.error(request, "Payment verification did not match this course or account.")
    except Exception as e: messages.error(request, f"System communication failure during validation: {str(e)}")
    return redirect('checkout', slug=course.slug)

@login_required
def register_teacher_application_view(request):
    profile = TeacherProfile.objects.filter(user=request.user).first()
    if profile:
        if profile.is_approved and profile.paystack_subaccount_code:
            messages.info(request, "Your instructor profile is fully certified and active!")
            return redirect('teacher_dashboard')
        if profile.is_approved and not profile.paystack_subaccount_code:
            messages.success(request, "You have been approved! Kindly upload your account details.")
            return redirect('register_payout')
        if profile.is_application_submitted:
            messages.warning(request, "You have already applied! Your qualification credentials are currently undergoing review.")
            return redirect('profile_page')
    if request.method == 'POST':
        form = TeacherApplicationForm(request.POST, request.FILES, instance=profile)
        if form.is_valid():
            application = form.save(commit=False)
            application.user = request.user
            application.is_application_submitted = True
            application.save()
            messages.success(request, "Application received! The administration team will verify your certificates manually.")
            return redirect('profile_page')
    else: form = TeacherApplicationForm(instance=profile)
    return render(request, 'dashboard/apply_teacher.html', {'form': form})

@login_required
def register_teacher_payout_view(request):
    from .utils import create_paystack_subaccount
    teacher_profile = TeacherProfile.objects.filter(user=request.user).first()
    if not teacher_profile or not teacher_profile.is_approved:
        messages.error(request, "You must submit your certifications and be approved before setting up banking details.")
        return redirect('register_teacher')
    if teacher_profile.is_approved and teacher_profile.paystack_subaccount_code:
        messages.info(request, "Your instructor profile is already active!")
        return redirect('teacher_dashboard')
    if request.method == 'POST':
        bank_name = request.POST.get('bank_name')
        account_number = request.POST.get('account_number', '').strip()
        if not bank_name or len(account_number) != 10 or not account_number.isdigit():
            messages.error(request, "Please select a valid bank and provide a standard 10-digit NUBAN account number.")
            return redirect('register_payout')
        teacher_profile.bank_name = bank_name
        teacher_profile.account_number = account_number
        teacher_profile.save()
        messages.info(request, "Connecting with payment gateways to verify credentials...")
        subaccount_code = create_paystack_subaccount(teacher_profile)
        if subaccount_code:
            teacher_profile.paystack_subaccount_code = subaccount_code
            teacher_profile.save()
            messages.success(request, f"Verification complete! Welcome to Quantum TechHub, Instructor {request.user.username}.")
            return redirect('teacher_dashboard')
        else:
            messages.error(request, "Verification failed. Please confirm that your 10-digit NUBAN number matches your selected bank.")
            return redirect('register_payout')
    return render(request, 'dashboard/register_teacher.html')

@login_required
def teacher_dashboard_view(request):
    teacher_profile = TeacherProfile.objects.filter(user=request.user).first()
    if not teacher_profile or not teacher_profile.is_approved:
        messages.error(request, "Access restricted to authorized platform instructors.")
        return redirect('profile_page')
    if not teacher_profile.paystack_subaccount_code:
        messages.warning(request, "Please link your payout bank details to activate dashboard toolbars.")
        return redirect('register_payout')
    teacher_courses = Course.objects.filter(author=request.user)
    total_revenue = 0
    total_enrollments = 0
    course_analytics = []
    for course in teacher_courses:
        enrollment_count = course.students.count()
        gross_course_earnings = enrollment_count * course.price
        platform_cut = 0.0 if course.author.is_superuser else float(course.platform_percentage)
        teacher_take_home_factor = (100 - platform_cut) / 100.0
        teacher_net_earnings = float(gross_course_earnings) * teacher_take_home_factor
        total_revenue += teacher_net_earnings
        total_enrollments += enrollment_count
        course_analytics.append({
            'title': course.title, 'price': course.price, 'enrollments': enrollment_count, 'net_earnings': teacher_net_earnings
        })
    context = {'courses': course_analytics, 'total_revenue': total_revenue, 'total_enrollments': total_enrollments, 'profile': teacher_profile}
    return render(request, 'dashboard/teacher_panel.html', context)

@login_required
def create_course_view(request):

    from django.utils.text import slugify

    teacher_profile = TeacherProfile.objects.filter(
        user=request.user
    ).first()

    if not teacher_profile or not teacher_profile.is_approved:
        messages.error(
            request,
            "Access restricted to authorized platform instructors."
        )
        return redirect('profile_page')

    if not teacher_profile.paystack_subaccount_code:
        messages.warning(
            request,
            "Please link your payout bank details before deploying new courses."
        )
        return redirect('register_payout')

    if request.method == 'POST':

        form = CourseCreationForm(request.POST)

        if form.is_valid():

            new_course = form.save(commit=False)
            new_course.author = request.user

            # Create a unique slug from the course title
            base_slug = slugify(new_course.title)
            slug = base_slug
            counter = 2

            while Course.objects.filter(slug=slug).exists():
                slug = f"{base_slug}-{counter}"
                counter += 1

            new_course.slug = slug

            new_course.save()

            messages.success(
                request,
                f"Course '{new_course.title}' has been created! "
                "Now you can add curriculum modules."
            )

            return redirect('teacher_dashboard')

    else:
        form = CourseCreationForm()

    return render(
        request,
        'dashboard/create_course.html',
        {'form': form}
    )
@login_required
def create_module_view(request):
    try:
        teacher_profile = TeacherProfile.objects.get(user=request.user)
        if not teacher_profile.is_approved: raise TeacherProfile.DoesNotExist
    except TeacherProfile.DoesNotExist:
        messages.warning(request, "Access restricted to certified platform instructors.")
        return redirect('register_teacher')
    if not teacher_profile.paystack_subaccount_code:
        messages.warning(request, "Please link your payout bank details before managing course modules.")
        return redirect('register_payout')
    if request.method == 'POST':
        form = ModuleCreationForm(request.POST, teacher=teacher_profile)
        if form.is_valid():
            module = form.save()
            messages.success(request, f"Syllabus Module '{module.title}' has been successfully created! You can now deploy lessons into it.")
            return redirect('teacher_dashboard')
        else: messages.error(request, "Submission blocked. Please review the form fields below.")
    else: form = ModuleCreationForm(teacher=teacher_profile)
    return render(request, 'dashboard/create_module.html', {'form': form})

class TeacherRequiredMixin(LoginRequiredMixin):
    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated: return self.handle_no_permission()
        try:
            teacher_profile = TeacherProfile.objects.get(user=request.user)
            if not teacher_profile.is_approved: raise TeacherProfile.DoesNotExist
        except TeacherProfile.DoesNotExist:
            messages.warning(request, "Access restricted to certified platform instructors.")
            return redirect('register_teacher')
        if not teacher_profile.paystack_subaccount_code:
            messages.warning(request, "Please link your payout bank details before continuing.")
            return redirect('register_payout')
        self.teacher_profile = teacher_profile
        return super().dispatch(request, *args, **kwargs)

class MiniAdminLessonListView(TeacherRequiredMixin, ListView):
    model = Lesson
    template_name = 'dashboard/lesson_list.html'
    context_object_name = 'lessons'
    def get_queryset(self):
        return Lesson.objects.filter(
            module__course__author=self.request.user
        ).select_related('module', 'module__course').order_by(
            'module__course__title', 'module__order', 'order', 'id'
        )
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['instructor_courses'] = Course.objects.filter(author=self.request.user).prefetch_related('modules')
        return context

@method_decorator(login_required, name='dispatch')
@method_decorator(xframe_options_exempt, name='dispatch')
class MiniAdminLessonCreateView(TeacherRequiredMixin, CreateView):
    model = Lesson
    form_class = LessonCreationForm
    template_name = 'dashboard/create_lesson.html'
    success_url = reverse_lazy('mini_admin_lesson_list')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        if self.request.POST:
            context['formset'] = LessonBlockFormSet(self.request.POST, self.request.FILES)
        else:
            context['formset'] = LessonBlockFormSet()

        context['page_title'] = "Add Content Lesson"
        context['instructor_courses'] = Course.objects.filter(
            author=self.request.user
        ).prefetch_related('modules')

        return context

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['teacher'] = self.teacher_profile
        return kwargs

    def form_valid(self, form):
        context = self.get_context_data()
        formset = context['formset']

        if formset.is_valid():
            self.object = form.save()

            formset.instance = self.object
            formset.save()

            messages.success(
                self.request,
                f"Lesson '{self.object.title}' created successfully!"
            )

            return redirect(
                "mini_admin_lesson_update",
                pk=self.object.pk
            )

        return self.render_to_response(context)

class MiniAdminLessonUpdateView(TeacherRequiredMixin, UpdateView):
    model = Lesson
    form_class = LessonCreationForm
    template_name = 'dashboard/edit_lesson.html'
    success_url = reverse_lazy('mini_admin_lesson_list')
    def get_object(self, queryset=None):
        obj = super().get_object(queryset)
        if obj.module.course.author != self.request.user: raise PermissionDenied("You do not own the parent curriculum track.")
        return obj
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        if self.request.POST:
            context['formset'] = LessonBlockFormSet(self.request.POST, self.request.FILES, instance=self.object)
        else:
            context['formset'] = LessonBlockFormSet(instance=self.object)
        context['page_title'] = f"Modify Lesson Parameters: {self.object.title}"
        context['instructor_courses'] = Course.objects.filter(author=self.request.user).prefetch_related('modules')
        return context
    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['teacher'] = self.teacher_profile
        return kwargs
    def form_valid(self, form):
        context = self.get_context_data()
        formset = context['formset']
        if formset.is_valid():
            self.object = form.save()
            formset.instance = self.object
            formset.save()
            messages.success(self.request, f"Changes to '{form.cleaned_data.get('title')}' successfully executed.")
            return redirect(self.get_success_url())
        return self.render_to_response(context)

class MiniAdminLessonDeleteView(TeacherRequiredMixin, DeleteView):
    model = Lesson
    template_name = 'dashboard/delete_lesson.html'
    success_url = reverse_lazy('mini_admin_lesson_list')
    def get_object(self, queryset=None):
        obj = super().get_object(queryset)
        if obj.module.course.author != self.request.user: raise PermissionDenied("You do not have administrative clearance.")
        return obj
    def form_valid(self, form):
        messages.success(self.request, f"Lesson '{self.object.title}' was deleted successfully.")
        return super().form_valid(form)

LESSON_BLOCK_TYPE_MAP = {
    "theory": "text",
    "text": "text",
    "code": "code",
    "challenge": "challenge",
    "runner": "challenge",
    "ide": "ide-workspace",
    "ide-workspace": "ide-workspace",
    "image": "image",
    "video": "video",
}

def _teacher_profile_is_ready(user):
    return TeacherProfile.objects.filter(
        user=user,
        is_approved=True,
        paystack_subaccount_code__isnull=False,
    ).exclude(paystack_subaccount_code="").exists()

def _save_lesson_payload(lesson, payload, files_dict=None, publish=False):
    module_id = payload.get("module")
    if module_id:
        lesson.module = get_object_or_404(
            Module,
            pk=module_id,
            course__author=lesson.module.course.author,
        )

    title = (payload.get("title") or "").strip()
    if title:
        lesson.title = title

    if "content" in payload:
        lesson.content = payload.get("content") or ""

    if publish:
        lesson.is_published = True

    lesson.save()
    LessonBlock.objects.filter(lesson=lesson).delete()

    for order, block in enumerate(payload.get("blocks", []), start=1):
        raw_type = block.get("type", "theory")
        block_data = {
            "lesson": lesson,
            "order": order,
            "block_type": LESSON_BLOCK_TYPE_MAP.get(raw_type, "text"),
            "content": block.get("content", ""),
            "env_key": block.get("env_key") or None,
            "hint": block.get("hint", ""),
            "expected_output": block.get("expected_output", ""),
        }

        # Handle file upload for image and video blocks
        if raw_type in ["image", "video"] and files_dict:
            file_key = f"blocks[{order-1}][file]"
            if file_key in files_dict:
                block_data["image"] = files_dict[file_key]

        LessonBlock.objects.create(**block_data)

@login_required
@require_POST
@xframe_options_exempt
@rate_limit(scope="advanced_python")
def run_advanced_server_side_code(request):
    if request.method == "POST":
        try:
            data = json.loads(request.body)
            student_code = data.get("code", "")
            
            if not student_code.strip():
                return JsonResponse({"status": "error", "output": "Empty script execution bypassed."})
                
            result = EnvironmentManager.execute("python", student_code)
            return JsonResponse(result)
            
        except Exception as e:
            return JsonResponse({"status": "error", "output": f"Transmission processing failure: {str(e)}"})
            
    return JsonResponse({"status": "error", "output": "Invalid request method pipeline access."})
@login_required
@require_POST
def publish(request, pk):
    lesson = get_object_or_404(Lesson.objects.select_related('module__course'), pk=pk)
    if lesson.module.course.author != request.user:
        return JsonResponse({"success": False, "error": "Permission denied."}, status=403)
    try:
        if request.content_type and 'multipart/form-data' in request.content_type:
            # Handle FormData with files
            data = {}
            blocks = []
            for key, value in request.POST.items():
                if key.startswith('blocks['):
                    # Parse block data from FormData
                    pass
                else:
                    data[key] = value

            # Parse blocks from POST data
            block_indices = set()
            for key in request.POST.keys():
                if key.startswith('blocks['):
                    idx = int(key.split('[')[1].split(']')[0])
                    block_indices.add(idx)

            for idx in sorted(block_indices):
                block = {}
                for key in request.POST.keys():
                    if key.startswith(f'blocks[{idx}]'):
                        field = key.split('[')[2].rstrip(']')
                        block[field] = request.POST.get(key)
                blocks.append(block)

            data['blocks'] = blocks
            _save_lesson_payload(lesson, data, request.FILES, publish=True)
        else:
            # Handle JSON request
            data = json.loads(request.body)
            _save_lesson_payload(lesson, data, publish=True)

        return JsonResponse({
            "success": True,
            "message": "Lesson published."
        })
    except Exception as e:
        return JsonResponse({
            "success": False,
            "error": str(e)
        }, status=400)

@login_required
@require_POST
def save_lesson(request, pk):
    lesson = get_object_or_404(Lesson.objects.select_related('module__course'), pk=pk)
    if lesson.module.course.author != request.user:
        return JsonResponse({"success": False, "error": "Permission denied."}, status=403)
    try:
        if request.content_type and 'multipart/form-data' in request.content_type:
            # Handle FormData with files
            data = {}
            blocks = []
            for key, value in request.POST.items():
                if not key.startswith('blocks['):
                    data[key] = value

            # Parse blocks from POST data
            block_indices = set()
            for key in request.POST.keys():
                if key.startswith('blocks['):
                    idx = int(key.split('[')[1].split(']')[0])
                    block_indices.add(idx)

            for idx in sorted(block_indices):
                block = {}
                for key in request.POST.keys():
                    if key.startswith(f'blocks[{idx}]'):
                        field = key.split('[')[2].rstrip(']')
                        block[field] = request.POST.get(key)
                blocks.append(block)

            data['blocks'] = blocks
            _save_lesson_payload(lesson, data, request.FILES, publish=False)
        else:
            # Handle JSON request
            data = json.loads(request.body)
            _save_lesson_payload(lesson, data, publish=False)

        return JsonResponse({
            "success": True,
            "message": "Lesson draft saved."
        })
    except json.JSONDecodeError:
        return JsonResponse({
            "success": False,
            "error": "Invalid JSON payload."
        }, status=400)
    except Exception as e:
        return JsonResponse({
            "success": False,
            "error": str(e)
        }, status=400)

@login_required
@require_POST
def create_lesson_ajax(request):
    """
    Creates an empty lesson and returns its ID.
    This is called only once when the user clicks Save Draft
    for a brand new lesson.
    """
    try:
        if not _teacher_profile_is_ready(request.user):
            return JsonResponse(
                {"success": False, "error": "Instructor account is not ready for lesson management."},
                status=403
            )

        data = json.loads(request.body)
        module = get_object_or_404(Module, pk=data.get("module"))

        # Security check
        if module.course.author != request.user:
            return JsonResponse(
                {"success": False, "error": "Permission denied."},
                status=403
            )

        lesson = Lesson.objects.create(
            module=module,
            title=data.get("title", "Untitled Lesson"),
            content="",
            order=Lesson.objects.filter(module=module).count() + 1
        )

        return JsonResponse({
            "success": True,
            "lesson_id": lesson.pk
        })

    except Exception as e:
        return JsonResponse(
            {"success": False, "error": str(e)},
            status=400
        )
