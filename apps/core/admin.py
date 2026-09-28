from django.contrib import admin
from django.contrib.auth.admin import GroupAdmin as BaseGroupAdmin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import Group, User
from django.utils.html import format_html
from unfold.admin import ModelAdmin, TabularInline
from unfold.forms import AdminPasswordChangeForm, UserChangeForm, UserCreationForm

from .admin_utils import SingletonAdmin
from .models import AccreditationLogo, Media, NotFoundLog, Redirect, SiteOptions, SocialLink

admin.site.site_header = "Site Safety Training"
admin.site.site_title = "Site Safety Training admin"
admin.site.index_title = "Website administration"

# Re-register auth models with the admin theme's forms.
admin.site.unregister(User)
admin.site.unregister(Group)


@admin.register(User)
class UserAdmin(BaseUserAdmin, ModelAdmin):
    form = UserChangeForm
    add_form = UserCreationForm
    change_password_form = AdminPasswordChangeForm


@admin.register(Group)
class GroupAdmin(BaseGroupAdmin, ModelAdmin):
    pass


class SocialLinkInline(TabularInline):
    model = SocialLink
    extra = 0


class AccreditationLogoInline(TabularInline):
    model = AccreditationLogo
    extra = 0
    raw_id_fields = ("image",)


@admin.register(SiteOptions)
class SiteOptionsAdmin(SingletonAdmin):
    inlines = [SocialLinkInline, AccreditationLogoInline]
    raw_id_fields = ("main_logo", "page_404_image")
    fieldsets = [
        ("General", {"fields": ("site_name", "tagline", "company_name", "main_logo", "posts_per_page")}),
        ("Contact details", {"fields": ("main_telephone_number", "main_email_address", "address", "google_map_link")}),
        ("Content blocks", {"classes": ("collapse",), "fields": ("banner_message", "about_us", "nebosh_about", "safety_about", "special_offer")}),
        ("404 page", {"classes": ("collapse",), "fields": ("page_404_image", "page_404_message")}),
        ("Sidebars", {"fields": ("enable_sidebar_on_posts", "enable_sidebar_on_pages")}),
        ("Order emails", {"fields": ("order_email_from_name", "order_email_footer")}),
    ]


@admin.register(Media)
class MediaAdmin(ModelAdmin):
    list_display = ("thumb", "title", "file", "mime_type", "uploaded_at")
    search_fields = ("title", "file", "alt")
    list_filter = ("mime_type",)
    readonly_fields = ("wp_id", "sizes", "width", "height")

    @admin.display(description="")
    def thumb(self, obj):
        if obj.mime_type.startswith("image/"):
            return format_html('<img src="{}" style="max-height:48px;max-width:80px">', obj.size_url("thumbnail"))
        return ""


@admin.register(Redirect)
class RedirectAdmin(ModelAdmin):
    list_display = ("old_path", "new_path", "permanent", "hits")
    search_fields = ("old_path", "new_path")


@admin.register(NotFoundLog)
class NotFoundLogAdmin(ModelAdmin):
    list_display = ("path", "hits", "referer", "last_seen")
    search_fields = ("path",)
    actions = ["make_redirect"]

    @admin.action(description="Create redirects to / for selected paths (edit them afterwards)")
    def make_redirect(self, request, queryset):
        for log in queryset:
            Redirect.objects.get_or_create(old_path=log.path, defaults={"new_path": "/"})
        queryset.delete()
