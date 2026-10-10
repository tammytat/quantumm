from django.db import models
from django.contrib.auth.models import User
from django.core.validators import MinValueValidator
from django.db.models.signals import post_save
from django.dispatch import receiver

# --- Existing Models ---

class Profile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    points = models.IntegerField(default=0)
    phone_number = models.CharField(max_length=15, blank=True, null=True)

    def get_rank(self):
        if self.points < 100: return "Novice Coder 🐣"
        elif self.points < 300: return "Tech Explorer 🔍"
        elif self.points < 600: return "Code Ninja 🥷"
        else: return "Robotics Master 🤖"

    def progress_to_next(self): return self.points % 100
    def __str__(self): return f"{self.user.username}'s Profile"

class TeacherProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='teacher_profile')
    first_name = models.CharField(max_length=150, blank=True)
    last_name = models.CharField(max_length=150, blank=True)
    phone_number = models.CharField(max_length=20, blank=True)
    years_of_experience = models.PositiveIntegerField(default=0)
    past_institutions = models.TextField(blank=True, null=True)
    certifications_held = models.TextField(blank=True, null=True)
    cv_upload = models.FileField(upload_to='teacher_documents/cv/', blank=True, null=True)
    certificate_upload = models.FileField(upload_to='teacher_documents/certificates/', blank=True, null=True)
    address = models.CharField(max_length=255, blank=True)
    highest_qualification = models.CharField(max_length=200, blank=True)
    specialization = models.CharField(max_length=200, blank=True)
    skills = models.TextField(blank=True)
    bank_name = models.CharField(max_length=100, blank=True, null=True)
    account_number = models.CharField(max_length=10, blank=True, null=True)
    paystack_subaccount_code = models.CharField(max_length=100, blank=True, null=True)
    is_application_submitted = models.BooleanField(default=False)
    is_approved = models.BooleanField(default=False)

    def __str__(self): return f"Teacher Application: {self.first_name} {self.last_name}"

class Course(models.Model):
    title = models.CharField(max_length=200)
    description = models.TextField()
    slug = models.SlugField(unique=True)
    image = models.ImageField(upload_to='courses/', blank=True, null=True)
    price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(0.01)],
    )
    students = models.ManyToManyField(User, related_name='enrolled_courses', blank=True)
    author = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='created_courses')
    course_type = models.CharField(max_length=20, default='python_core')
    platform_percentage = models.PositiveIntegerField(default=30) 

    def __str__(self): return self.title

class Module(models.Model):
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name='modules')
    title = models.CharField(max_length=200)
    order = models.PositiveIntegerField(default=1)
    
    class Meta: 
        ordering = ['order']
    
    def __str__(self): return f"{self.course.title} - {self.title}"

class Lesson(models.Model):
    module = models.ForeignKey(
        Module,
        on_delete=models.CASCADE,
        related_name='lessons'
    )

    title = models.CharField(max_length=200)
    content = models.TextField(blank=True, null=True)
    order = models.PositiveIntegerField(default=1)

    is_published = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['order']

    def __str__(self):
        return f"{self.order}. {self.title}"


# ← THIS LINE MUST EXIST
class LessonBlock(models.Model):

    BLOCK_TYPES = (
        ('text', 'Theory/Text'),
        ('image', 'Image Content'),
        ('video', 'Video Content'),
        ('dataset', 'Dataset File'),
        ('code', 'Code Snippet'),
        ('challenge', 'Interactive Challenge'),
        ('ide-workspace', 'IDE Sandbox'),
    )

    ENV_CHOICES = (
        ('python', 'Python Sandbox'),
        ('advanced_python_engine', 'Advanced Python'),
        ('arduino_flasher', 'Arduino Flasher'),
        ('circuit', 'Circuit Simulator'),
        ('circuit_simulator', 'Circuit Simulator'),
        ('jupyter', 'JupyterLite Notebook'),
        ('jupyter_notebook', 'Jupyter Notebook'),
        ('wokwi', 'Wokwi Robotics Simulator'),
        ('robotics', 'Robotics Simulator'),
                ('cyber', 'Cyber Lab (Simulated)'),
        ('office_utility_excel', 'Excel Utility'),
        ('office_utility_powerpoint', 'PowerPoint Utility'),
        ('office_utility', 'General Office'),
        ('powerbi', 'Power BI'),
        ('python_sandbox', 'Python Sandbox'),
        ('security_terminal', 'Cyber Lab (Simulated)'),
    )

    lesson = models.ForeignKey(
        Lesson,
        related_name='blocks',
        on_delete=models.CASCADE
    )

    block_type = models.CharField(
        max_length=20,
        choices=BLOCK_TYPES,
        default='text'
    )

    order = models.PositiveIntegerField(default=1)

    env_key = models.CharField(
        max_length=50,
        choices=ENV_CHOICES,
        blank=True,
        null=True
    )

    content = models.TextField(blank=True, null=True)
    image = models.ImageField(upload_to='lesson_images/', blank=True, null=True)
    dataset_file = models.FileField(upload_to='lesson_datasets/', blank=True, null=True)
    hint = models.TextField(blank=True, null=True)
    expected_output = models.TextField(blank=True, null=True)

    class Meta:
        ordering = ['order']

    def __str__(self):
        return f"{self.order}. {self.block_type} for {self.lesson.title}"


class LessonCompletion(models.Model):
    """Records a learner's first successful completion of a lesson.

    Used to award XP exactly once per lesson rather than on every correct
    submission (which previously allowed farming points by re-running code).
    """
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='lesson_completions')
    lesson = models.ForeignKey(Lesson, on_delete=models.CASCADE, related_name='completions')
    completed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('user', 'lesson')
        ordering = ['-completed_at']

    def __str__(self):
        return f"{self.user.username} completed {self.lesson.title}"


class Payment(models.Model):
    """Audit record for verified Paystack transactions.

    Provides idempotency (a reference can only be recorded once) and a payment
    history for reporting.
    """
    reference = models.CharField(max_length=100, unique=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='payments')
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name='payments')
    amount_kobo = models.PositiveIntegerField()
    verified = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.reference} ({'verified' if self.verified else 'pending'})"


# --- Signals ---

@receiver(post_save, sender=User)
def manage_user_profile(sender, instance, created, **kwargs):
    # Only create the profile once. Forcing a save on every User.save() caused
    # redundant writes and should be avoided.
    if created:
        Profile.objects.get_or_create(user=instance)
