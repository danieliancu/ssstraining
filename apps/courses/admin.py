from django.contrib import admin
from mptt.admin import MPTTModelAdmin

from apps.blog.admin import TermAdmin
from apps.core.admin_utils import SEO_FIELDSET, ContentAdmin

from .models import NeboshCourse, NeboshCourseTerm, SafetyCourse, SafetyCourseTerm


class CourseAdmin(ContentAdmin):
    filter_horizontal = ("terms",)
    list_display = ("title", "status", "menu_order", "modified_at")
    extra_fieldsets = (("Categories", {"fields": ("terms",),
                                       "description": "Course price, content blocks and dates are in Advanced → acf."}),)


admin.site.register(NeboshCourse, CourseAdmin)
admin.site.register(SafetyCourse, CourseAdmin)


class CourseTermAdmin(MPTTModelAdmin, TermAdmin):
    fieldsets = [(None, {"fields": ("name", "slug", "parent", "description", "acf")}), SEO_FIELDSET]


admin.site.register(NeboshCourseTerm, CourseTermAdmin)
admin.site.register(SafetyCourseTerm, CourseTermAdmin)
