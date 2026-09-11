from rest_framework.routers import DefaultRouter
from .api_views import EvaluationViewSet, GradeViewSet, SemesterAverageViewSet

router = DefaultRouter()
router.register(r'evaluations', EvaluationViewSet,    basename='evaluation')
router.register(r'grades',      GradeViewSet,         basename='grade')
router.register(r'averages',    SemesterAverageViewSet, basename='semester-average')

urlpatterns = router.urls
