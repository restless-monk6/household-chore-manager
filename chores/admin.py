from django.contrib import admin

from .models import Chore, ChoreEvent, Member, PointsAward, ReminderLog


@admin.register(Member)
class MemberAdmin(admin.ModelAdmin):
    list_display = ["name", "is_child", "is_active"]


@admin.register(Chore)
class ChoreAdmin(admin.ModelAdmin):
    list_display = ["name", "category", "assigned_to", "due_at", "status", "points"]
    list_filter = ["status", "category", "assigned_to"]
    search_fields = ["name"]


@admin.register(ChoreEvent)
class ChoreEventAdmin(admin.ModelAdmin):
    list_display = ["chore", "kind", "actor", "at"]
    list_filter = ["kind"]


@admin.register(PointsAward)
class PointsAwardAdmin(admin.ModelAdmin):
    list_display = ["member", "chore_name", "points", "pauses", "reason", "awarded_at"]
    list_filter = ["reason", "member"]


admin.site.register(ReminderLog)
