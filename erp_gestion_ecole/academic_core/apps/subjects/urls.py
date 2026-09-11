from django.urls import path
from . import views

app_name = 'subjects'

urlpatterns = [
    path('',                            views.SubjectListView.as_view(),   name='list'),
    path('create/',                     views.SubjectCreateView.as_view(), name='create'),
    path('<int:pk>/edit/',              views.SubjectUpdateView.as_view(), name='edit'),
    path('<int:pk>/delete/',            views.SubjectDeleteView.as_view(), name='delete'),
    path('semester/<int:pk>/dupliquer/', views.semester_duplicate,         name='semester_duplicate'),
]
