from django import template
from django.utils.html import format_html, format_html_join
from django.utils.safestring import mark_safe

register = template.Library()


@register.filter
def bullet_list(text):
    """
    Affiche le contenu portail d'une rubrique de filière (objectifs/
    compétences/débouchés/modalités d'admission).

    Deux cas :
    - Contenu saisi via l'éditeur à puces (voir filiere_content_edit.html,
      ProgramContentForm.sanitize_rich_text) : déjà du HTML sanitisé
      (<ul>/<ol>/<li>/<b>/<i>...) — affiché tel quel, en confiance (nettoyé
      à l'écriture, jamais à la lecture).
    - Contenu hérité, saisi avant l'éditeur à puces (texte brut, une idée
      par ligne, aucune balise) : converti à la volée en liste à puces, le
      texte de chaque ligne étant échappé (jamais du HTML de confiance).
    """
    if not text:
        return ''
    if '<' in text:
        return mark_safe(text)
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return ''
    items = format_html_join('', '<li>{}</li>', ((line,) for line in lines))
    return format_html('<ul class="bullet-list">{}</ul>', items)
