"""
Liste de pays de naissance et nationalités associées (gentilés français),
utilisée pour dériver automatiquement `Student.nationality` à partir de
`Student.country_of_birth`. Volontairement une liste maison (pas de paquet
type django-countries) : aucun paquet ne fournit de gentilés français
genrés prêts à l'emploi, et cela évite une nouvelle dépendance pour un
besoin purement local. Suit la même convention que `Teacher.nationalite`
(texte libre, gentilé féminin par défaut, ex. "Sénégalaise").

Couvre en priorité l'Afrique de l'Ouest (CEDEAO) et le reste de l'Afrique,
puis les principaux pays partenaires internationaux. `AUTRE` est prévu pour
les cas non couverts (nationalité alors saisie manuellement).
"""

AUTRE = 'AUTRE'

COUNTRY_NATIONALITY = {
    # ── Afrique de l'Ouest (CEDEAO) ─────────────────────────────────────
    'Sénégal':                 'Sénégalaise',
    "Côte d'Ivoire":           'Ivoirienne',
    'Mali':                    'Malienne',
    'Mauritanie':               'Mauritanienne',
    'Guinée':                  'Guinéenne',
    'Guinée-Bissau':           'Bissau-Guinéenne',
    'Gambie':                  'Gambienne',
    'Burkina Faso':            'Burkinabè',
    'Bénin':                   'Béninoise',
    'Togo':                    'Togolaise',
    'Niger':                   'Nigérienne',
    'Nigéria':                 'Nigériane',
    'Ghana':                   'Ghanéenne',
    'Cap-Vert':                'Cap-Verdienne',
    'Sierra Leone':            'Sierra-Léonaise',
    'Liberia':                 'Libérienne',

    # ── Afrique centrale ─────────────────────────────────────────────────
    'Cameroun':                'Camerounaise',
    'Gabon':                   'Gabonaise',
    'Congo':                   'Congolaise',
    'République démocratique du Congo': 'Congolaise (RDC)',
    'Tchad':                   'Tchadienne',
    'République centrafricaine': 'Centrafricaine',
    'Guinée équatoriale':      'Équato-guinéenne',

    # ── Afrique du Nord / Maghreb ────────────────────────────────────────
    'Maroc':                   'Marocaine',
    'Algérie':                 'Algérienne',
    'Tunisie':                 'Tunisienne',
    'Libye':                   'Libyenne',
    'Égypte':                  'Égyptienne',

    # ── Afrique de l'Est ─────────────────────────────────────────────────
    'Éthiopie':                'Éthiopienne',
    'Kenya':                   'Kényane',
    'Tanzanie':                'Tanzanienne',
    'Ouganda':                 'Ougandaise',
    'Rwanda':                  'Rwandaise',
    'Burundi':                 'Burundaise',
    'Somalie':                 'Somalienne',
    'Djibouti':                'Djiboutienne',
    'Soudan':                  'Soudanaise',
    'Soudan du Sud':           'Sud-Soudanaise',
    'Érythrée':                'Érythréenne',

    # ── Afrique australe ─────────────────────────────────────────────────
    'Afrique du Sud':          'Sud-Africaine',
    'Madagascar':              'Malgache',
    'Mozambique':              'Mozambicaine',
    'Zambie':                  'Zambienne',
    'Zimbabwe':                'Zimbabwéenne',
    'Angola':                  'Angolaise',
    'Namibie':                 'Namibienne',
    'Botswana':                'Botswanaise',
    'Comores':                 'Comorienne',
    'Malawi':                  'Malawite',
    'Lesotho':                 'Basotho',
    'Eswatini':                'Swazie',
    'Sao Tomé-et-Principe':    'Santoméenne',

    # ── Europe ──────────────────────────────────────────────────────────
    'France':                  'Française',
    'Belgique':                'Belge',
    'Suisse':                  'Suisse',
    'Allemagne':               'Allemande',
    'Italie':                  'Italienne',
    'Espagne':                 'Espagnole',
    'Portugal':                'Portugaise',
    'Royaume-Uni':             'Britannique',
    'Pays-Bas':                'Néerlandaise',
    'Russie':                  'Russe',
    'Turquie':                 'Turque',

    # ── Amériques ───────────────────────────────────────────────────────
    'États-Unis':              'Américaine',
    'Canada':                  'Canadienne',
    'Brésil':                  'Brésilienne',
    'Haïti':                   'Haïtienne',

    # ── Moyen-Orient ────────────────────────────────────────────────────
    'Liban':                   'Libanaise',
    'Syrie':                   'Syrienne',
    'Arabie saoudite':         'Saoudienne',
    'Émirats arabes unis':     'Émirienne',
    'Qatar':                   'Qatarienne',
    'Jordanie':                'Jordanienne',
    'Irak':                    'Irakienne',
    'Iran':                    'Iranienne',
    'Yémen':                   'Yéménite',

    # ── Asie / Océanie ──────────────────────────────────────────────────
    'Chine':                   'Chinoise',
    'Inde':                    'Indienne',
    'Japon':                   'Japonaise',
    'Corée du Sud':            'Sud-Coréenne',
    'Vietnam':                 'Vietnamienne',
    'Pakistan':                'Pakistanaise',
    'Afghanistan':             'Afghane',
    'Indonésie':               'Indonésienne',
    'Malaisie':                'Malaisienne',
    'Philippines':             'Philippine',
    'Thaïlande':                'Thaïlandaise',
    'Australie':               'Australienne',

    # ── Autre ───────────────────────────────────────────────────────────
    AUTRE:                     'Autre',
}

COUNTRY_CHOICES = (
    [('', '— Sélectionner un pays —')]
    + sorted(((name, name) for name in COUNTRY_NATIONALITY if name != AUTRE), key=lambda c: c[0])
    + [(AUTRE, 'Autre pays (préciser la nationalité)')]
)
