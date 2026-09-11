from .registry import TOOL_REGISTRY, register_tool

# Importés pour leur effet de bord : chaque module peuple TOOL_REGISTRY
# via le décorateur @register_tool au chargement.
from . import student_tools, teacher_tools, admin_tools, super_admin_tools, notification_tools  # noqa: F401,E402

__all__ = ['TOOL_REGISTRY', 'register_tool']
