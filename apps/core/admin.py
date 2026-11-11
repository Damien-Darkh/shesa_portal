from django.contrib import admin

from .models import Department, Notification, SearchIndex, TimeAttendance, UserProfile


@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):
    list_display = ("name", "parent", "manager")
    search_fields = ("name",)


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "job_title", "department", "office_location")
    search_fields = ("user__email", "job_title")
    list_filter = ("department",)


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ("user", "notification_type", "title", "is_read", "sent_at")
    list_filter = ("notification_type", "is_read")


@admin.register(TimeAttendance)
class TimeAttendanceAdmin(admin.ModelAdmin):
    list_display = ("user", "clock_in", "clock_out", "duration_minutes")


@admin.register(SearchIndex)
class SearchIndexAdmin(admin.ModelAdmin):
    list_display = ("document_type", "document_id", "title")
    search_fields = ("title",)
