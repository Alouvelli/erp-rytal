from django.urls import path
from . import views

app_name = 'reports'

urlpatterns = [
    path('',                                               views.reports_index,       name='index'),
    path('bulletin/<int:student_id>/<int:semester_id>/',   views.bulletin_pdf,        name='bulletin_pdf'),
    path('teacher/<int:teacher_id>/<int:year_id>/pdf/',    views.teacher_report_pdf,  name='teacher_pdf'),
    path('absences/<int:class_id>/<int:semester_id>/pdf/', views.absence_report_pdf,  name='absence_pdf'),
    path('grades/<int:class_id>/<int:semester_id>/excel/', views.grades_excel,        name='grades_excel'),
    path('timetable/<int:semester_id>/excel/',             views.timetable_excel,     name='timetable_excel'),
]
