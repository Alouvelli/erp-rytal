from django.contrib import admin
from .models import ChatConversation, ChatMessage


class ChatMessageInline(admin.TabularInline):
    model = ChatMessage
    extra = 0
    readonly_fields = ['role', 'content', 'is_welcome', 'created_at']
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(ChatConversation)
class ChatConversationAdmin(admin.ModelAdmin):
    list_display = ['user', 'created_at', 'updated_at']
    search_fields = ['user__username', 'user__email', 'user__first_name', 'user__last_name']
    readonly_fields = ['user', 'created_at', 'updated_at']
    inlines = [ChatMessageInline]

    def has_add_permission(self, request):
        return False
