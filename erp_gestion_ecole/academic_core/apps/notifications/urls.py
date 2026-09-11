from django.urls import path
from . import views

app_name = 'notifications'

urlpatterns = [
    path('',                      views.NotificationListView.as_view(), name='list'),
    path('<int:pk>/read/',         views.mark_read,                      name='mark_read'),
    path('mark-all-read/',         views.mark_all_read,                  name='mark_all_read'),
    path('<int:pk>/delete/',        views.delete_notification,            name='delete'),
    path('delete-all/',             views.delete_all_notifications,       name='delete_all'),
    path('notifier-absence/',      views.notify_teacher_absence,         name='notify_absence'),
]
