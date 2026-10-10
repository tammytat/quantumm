from django import forms
from django.forms import inlineformset_factory
from .models import Course, Lesson, Module, LessonBlock, TeacherProfile

# --- CENTRALIZED STYLING CLASSES ---
DARK_INPUT_CLASS = "w-full bg-slate-950 border border-slate-800 rounded-xl px-3 py-2 text-sm text-white placeholder-slate-700 focus:outline-none focus:border-emerald-500 transition"
DARK_SELECT_CLASS = "w-full bg-slate-950 border border-slate-800 rounded-xl px-3 py-2 text-sm text-slate-300 focus:outline-none focus:border-emerald-500 transition cursor-pointer"
DARK_TEXTAREA_CLASS = "w-full bg-slate-950 border border-slate-800 rounded-xl px-3 py-2 text-sm text-white placeholder-slate-700 focus:outline-none focus:border-emerald-500 transition resize-none"
BUILDER_INPUT_CLASS = "frontend-builder-input" # Used by lesson_builder.js

# --- CENTRALIZED LESSON BLOCK FORM ---
class LessonBlockForm(forms.ModelForm):
    class Meta:
        model = LessonBlock
        fields = ['order', 'block_type', 'env_key', 'content', 'image', 'hint', 'expected_output']
        widgets = {
            'block_type': forms.Select(attrs={'class': f'{DARK_SELECT_CLASS} {BUILDER_INPUT_CLASS}'}),
            'env_key': forms.Select(attrs={'class': f'{DARK_SELECT_CLASS} {BUILDER_INPUT_CLASS}'}),
            'content': forms.Textarea(attrs={'class': f'{DARK_TEXTAREA_CLASS} {BUILDER_INPUT_CLASS}'}),
            'image': forms.FileInput(attrs={'class': f'{DARK_INPUT_CLASS} {BUILDER_INPUT_CLASS}'}),
            'hint': forms.TextInput(attrs={'class': f'{DARK_INPUT_CLASS} {BUILDER_INPUT_CLASS}'}),
            'expected_output': forms.TextInput(attrs={'class': f'{DARK_INPUT_CLASS} {BUILDER_INPUT_CLASS}'}),
            'order': forms.HiddenInput(),
        }

# --- INLINE FORMSET FOR LESSON BLOCKS ---
LessonBlockFormSet = inlineformset_factory(
    Lesson, 
    LessonBlock, 
    form=LessonBlockForm, 
    extra=1, 
    can_delete=True
)

# --- COURSE CREATION FORM ---
class CourseCreationForm(forms.ModelForm):
    class Meta:
        model = Course
        fields = ['title', 'description', 'image', 'price', 'course_type']
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields:
            self.fields[field].widget.attrs.update({'class': 'form-control bg-white text-dark border p-3 rounded-3'})

# --- MODULE CREATION FORM ---
class ModuleCreationForm(forms.ModelForm):
    class Meta:
        model = Module
        fields = ['course', 'title', 'order']
    def __init__(self, *args, **kwargs):
        teacher = kwargs.pop('teacher', None)
        super().__init__(*args, **kwargs)
        if teacher: self.fields['course'].queryset = Course.objects.filter(author=teacher.user).order_by('title')
        for field in self.fields:
            self.fields[field].widget.attrs.update({'class': 'form-control bg-white text-dark border p-3 rounded-3'})

# --- INSTRUCTOR LESSON CREATION FORM ---
class LessonCreationForm(forms.ModelForm):
    class Meta:
        model = Lesson
        fields = ['module', 'title', 'content', 'order'] 
    def __init__(self, *args, **kwargs):
        self.teacher = kwargs.pop('teacher', None)
        super().__init__(*args, **kwargs)
        if 'module' in self.fields:
            self.fields['module'].widget.attrs.update({'class': DARK_SELECT_CLASS})
            if self.teacher:
                from .models import Module
                self.fields['module'].queryset = Module.objects.filter(course__author=self.teacher.user)
        self.fields['title'].widget.attrs.update({'class': DARK_INPUT_CLASS, 'placeholder': 'e.g., Working with Ultrasonic Sensors'})
        self.fields['content'].widget.attrs.update({'class': DARK_TEXTAREA_CLASS})

# --- TEACHER SCREENING & VETTING FORM ---
class TeacherApplicationForm(forms.ModelForm):
    class Meta:
        model = TeacherProfile
        fields = ['first_name', 'last_name', 'phone_number', 'years_of_experience', 'past_institutions', 'certifications_held', 'cv_upload', 'certificate_upload']
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        std_class = "mt-1 block w-full rounded-lg border border-slate-700 bg-slate-900 px-4 py-2.5 text-slate-100 focus:border-blue-500 focus:outline-none transition duration-150"
        file_class = "mt-1 block w-full text-sm text-slate-400 border border-slate-700 rounded-lg bg-slate-900 file:bg-blue-600 file:text-white"
        for fn, f in self.fields.items():
            f.widget.attrs.update({'class': file_class if fn in ['cv_upload', 'certificate_upload'] else std_class})