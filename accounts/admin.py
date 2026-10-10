from django.contrib import admin
from django.contrib import messages
from adminsortable2.admin import SortableStackedInline, SortableAdminBase
from .models import TeacherProfile, Course, Module, Lesson, LessonBlock, LessonCompletion, Payment
from .forms import LessonBlockForm

# =====================================================================
# 1. SORTABLE INLINE LAYOUTS
# =====================================================================

class LessonBlockInline(SortableStackedInline):
    model = LessonBlock
    form = LessonBlockForm
    extra = 0
    # Custom template to enable side-by-side builder UI
    template = 'admin/edit_inline/stacked.html' 
    classes = ['collapse', 'builder-row']
    fields = ('order', 'block_type', 'env_key', 'content', 'hint', 'expected_output', 'image')

class LessonInline(SortableStackedInline):
    model = Lesson
    extra = 0
    fields = ('title', 'order')

class ModuleInline(SortableStackedInline):
    model = Module
    extra = 0
    fields = ('title', 'order')

# =====================================================================
# 2. MODEL ADMIN REGISTRATIONS
# =====================================================================

@admin.register(TeacherProfile)
class TeacherProfileAdmin(admin.ModelAdmin):
    list_display = ('first_name', 'last_name', 'phone_number', 'is_approved')
    list_filter = ('is_approved',)
    search_fields = ('first_name', 'last_name')
    readonly_fields = ('cv_upload', 'certificate_upload')
    actions = ['approve_applications', 'reject_applications']

    @admin.action(description='Approve selected applications')
    def approve_applications(self, request, queryset):
        queryset.update(is_approved=True)
        self.message_user(request, "Selected applications approved.", messages.SUCCESS)

    @admin.action(description='Reject selected applications')
    def reject_applications(self, request, queryset):
        queryset.update(is_approved=False)
        self.message_user(request, "Selected applications rejected.", messages.WARNING)

@admin.register(Course)
class CourseAdmin(SortableAdminBase, admin.ModelAdmin):
    list_display = ('title', 'price', 'course_type')
    inlines = [ModuleInline]

@admin.register(Module)
class ModuleAdmin(SortableAdminBase, admin.ModelAdmin):
    list_display = ('title', 'course', 'order')
    list_filter = ('course',)
    inlines = [LessonInline]

@admin.register(Lesson)
class LessonAdmin(SortableAdminBase, admin.ModelAdmin):
    fieldsets = [
        ('Lesson Metadata', {
            'fields': ['module', 'title', 'order'],
            'classes': ['wide']
        }),
    ]
    inlines = [LessonBlockInline] 

    list_display = ('title', 'get_course', 'module', 'order')
    list_filter = ('module__course',)

    @admin.display(description='Course Track')
    def get_course(self, obj):
        return obj.module.course.title

    class Media:
        css = {'all': ('css/lesson_builder.css',)}
        js = ('js/lesson_builder.js',)

@admin.register(LessonBlock)
class LessonBlockAdmin(admin.ModelAdmin):
    form = LessonBlockForm
    list_display = ('lesson', 'block_type', 'env_key', 'order')
    list_filter = ('block_type', 'env_key', 'lesson')
    search_fields = ('lesson__title', 'content', 'hint', 'expected_output')


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    """Read-only audit trail of verified Paystack transactions."""

    list_display = ('reference', 'user', 'course', 'amount_naira', 'verified', 'created_at')
    list_filter = ('verified', 'created_at', 'course')
    search_fields = ('reference', 'user__username', 'user__email', 'course__title')
    date_hierarchy = 'created_at'
    ordering = ('-created_at',)

    # Payments are created only by the verified Paystack callback; never by hand.
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.display(description='Amount', ordering='amount_kobo')
    def amount_naira(self, obj):
        return f"₦{obj.amount_kobo / 100:,.2f}"


@admin.register(LessonCompletion)
class LessonCompletionAdmin(admin.ModelAdmin):
    """Read-only audit trail of lesson completions (XP is awarded here)."""

    list_display = ('user', 'lesson', 'course', 'completed_at')
    list_filter = ('completed_at', 'lesson__module__course')
    search_fields = ('user__username', 'user__email', 'lesson__title')
    date_hierarchy = 'completed_at'
    ordering = ('-completed_at',)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.display(description='Course')
    def course(self, obj):
        return obj.lesson.module.course.title
