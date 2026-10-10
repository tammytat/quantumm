from django.urls import path
from . import views
from django.views.generic import TemplateView

urlpatterns = [
    # --- Platform Landing & Dashboard ---
    path('', views.index, name='index'),

    # --- Dedicated Public Course Catalog ---
    path('courses/', views.our_courses_view, name='our_courses'),

    # --- Authentication & Profile Routes ---
    path('signup/', views.signup_view, name='signup'),
    path('login/', views.login_view, name='login'),
    path('accounts/login/', views.login_view),
    path('profile/', views.profile_view, name='profile_page'),
    path('logout/', views.logout_view, name='logout'),

        # --- Static Informational Pages ---
    path('contact/', views.contact, name='contact'),
    path('services/', views.services, name='services'),
    path('about/', views.about, name='about'),

    # --- Course & Lesson Navigation Ecosystem ---
    path('course/<slug:slug>/', views.single_course_view, name='single_course_view'),
    path('course/<slug:slug>/lesson/<int:lesson_id>/', views.lesson_detail, name='lesson_detail'),
    path('api/validate-code/', views.generic_validate_code, name='validate_code'),
    path('api/v1/execute/', views.execute_environment, name='execute_environment'),
    path('api/v1/upload-dataset/', views.upload_dataset, name='upload_dataset'),
    path('api/v1/environments/<str:env_key>/', views.environment_config, name='environment_config'),

    # --- Payment Gateways: STUDENT PURCHASE ---
    path('course/<slug:slug>/checkout/', views.checkout, name='checkout'),
    path('course/<slug:slug>/verify/', views.payment_success, name='payment_success'),

    # --- Multi-Tier Instructor Marketplace & Onboarding Routes ---
    path('dashboard/instructor/apply/', views.register_teacher_application_view, name='register_teacher'),
    path('dashboard/instructor/payout-setup/', views.register_teacher_payout_view, name='register_payout'),
    path('dashboard/instructor/', views.teacher_dashboard_view, name='teacher_dashboard'),

    # --- Core Instructor Content Publishing Pipeline ---
    path('dashboard/instructor/course/new/', views.create_course_view, name='create_course'),
    path('dashboard/instructor/module/new/', views.create_module_view, name='create_module'),

    # --- MINI ADMIN STUDIO LESSON MANAGEMENT ROUTES ---
  
    path('studio/lessons/', views.MiniAdminLessonListView.as_view(), name='mini_admin_lesson_list'),
    path('studio/lessons/add/', views.MiniAdminLessonCreateView.as_view(), name='mini_admin_lesson_create'),
    path('studio/lessons/<int:pk>/edit/', views.MiniAdminLessonUpdateView.as_view(), name='mini_admin_lesson_update'),
    path('studio/lessons/<int:pk>/delete/', views.MiniAdminLessonDeleteView.as_view(), name='mini_admin_lesson_delete'),
    # --- Advanced Python API ---
    path('studio/api/run-advanced-python/', views.run_advanced_server_side_code, name='run_advanced_python_api'),

    # --- Payment Gateways: INSTRUCTOR SUBACCOUNT SETUP ---
    path('checkout/<slug:slug>/', views.checkout, name='instructor_checkout_link'),
    path('dashboard/payment/success/<slug:slug>/', views.payment_success, name='instructor_payment_success'),

    path('jupyter/', TemplateView.as_view(template_name='jupyter_lite.html')),
    path('check-code/<int:lesson_id>/', views.check_code, name='check_code'),

    # --- Environment Gateway Routing ---
    path('environments/<str:env_key>/', views.env_gateway, name='env_gateway'),
    
    path(
        "lessons/create/",
        views.create_lesson_ajax,
        name="create_lesson_ajax",
    ),
    
    path(
        'lessons/<int:pk>/save/',
        views.save_lesson,
        name='save_lesson'
    ),
    path(
        'lessons/<int:pk>/publish/',
        views.publish,
        name='publish_lesson'
    ),
]
