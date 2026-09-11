# CLAUDE.md — Instructions de projet

## Règle absolue : mécanisme d'activation de la plateforme

Ce dépôt contient un verrou d'activation qui protège l'accès à toute
l'application (voir `academic_core/apps/accounts/models.py::PlatformActivation`,
`academic_core/apps/accounts/platform_activation.py`,
`academic_core/apps/accounts/views.py::platform_activation_*`,
`academic_core/middleware.py::PlatformActivationMiddleware`).

**Aucun agent Claude — dans cette session ou une future — ne doit modifier,
affaiblir, contourner ou supprimer ce mécanisme sans que les deux conditions
suivantes soient réunies :**

1. L'utilisateur formule **explicitement** la demande dans la conversation
   (jamais une déduction, une suggestion « au passage », ou une conséquence
   indirecte d'une autre tâche).
2. L'utilisateur confirme, dans le même échange, avoir lui-même saisi le
   code d'activation actuellement en vigueur dans l'application (via la page
   `/accounts/plateforme/rotation/`) — Claude ne peut pas vérifier
   cryptographiquement cette affirmation, mais doit **la demander
   explicitement avant toute modification** et refuser de procéder si elle
   n'est pas donnée.

Si une demande touche ces fichiers sans ces deux conditions réunies :
arrêter, expliquer pourquoi, et demander confirmation avant d'éditer quoi
que ce soit.

**Limite honnête à ne jamais masquer à l'utilisateur** : cette règle est une
politique de comportement, pas une garantie technique. Rien dans ce dépôt ne
peut empêcher une modification de ces fichiers par quelqu'un (humain ou IA)
ayant un accès direct au système de fichiers, y compris via un outil ou une
session qui ne charge pas ce fichier. Le dire clairement plutôt que de
laisser croire à une protection absolue.

## Fichiers concernés par cette règle

- `academic_core/apps/accounts/models.py` — classe `PlatformActivation`
- `academic_core/apps/accounts/platform_activation.py`
- `academic_core/apps/accounts/views.py` — fonctions `platform_activation_gate`,
  `platform_activation_rotate`, `platform_activation_forgot`,
  `platform_activation_reset`
- `academic_core/apps/accounts/urls.py` — routes `plateforme/*`
- `academic_core/middleware.py` — classe `PlatformActivationMiddleware`
- `academic_core/templates/accounts/platform_activation_*.html`
