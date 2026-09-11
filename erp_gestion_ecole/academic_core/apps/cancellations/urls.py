from django.urls import path
from . import views

app_name = 'cancellations'

urlpatterns = [
    path('',                                              views.cancellation_dashboard, name='list'),
    path('<int:entry_pk>/<str:session_date_str>/action/', views.cancel_or_postpone,    name='action'),
    path('<int:pk>/restore/',                             views.restore_session,        name='restore'),
]
