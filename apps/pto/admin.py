from django.contrib import admin

from .models import LeaveApprovalWorkflow, LeaveBalance, LeaveRequest


@admin.register(LeaveBalance)
class LeaveBalanceAdmin(admin.ModelAdmin):
    list_display = ("user", "year", "leave_type", "accrued_days", "carryover_days", "used_days", "pending_days")
    list_filter = ("year", "leave_type")
    search_fields = ("user__email",)


class ApprovalInline(admin.TabularInline):
    model = LeaveApprovalWorkflow
    extra = 0
    readonly_fields = ("step", "approver", "status", "comment", "completed_at")


@admin.register(LeaveRequest)
class LeaveRequestAdmin(admin.ModelAdmin):
    list_display = ("user", "leave_type", "start_date", "end_date", "days_requested", "status")
    list_filter = ("status", "leave_type")
    search_fields = ("user__email",)
    inlines = [ApprovalInline]
