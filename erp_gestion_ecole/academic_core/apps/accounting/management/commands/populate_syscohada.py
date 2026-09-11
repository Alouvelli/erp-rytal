"""
Commande : python manage.py populate_syscohada
Insère tous les comptes du Plan Comptable SYSCOHADA Révisé adaptés à un
établissement d'enseignement supérieur. Les comptes déjà présents (même
matricule) sont ignorés (get_or_create).
"""
from django.core.management.base import BaseCommand
from django.db import transaction


COMPTES = [
    # ── CLASSE 1 — Comptes de ressources durables ────────────────────────────
    ('10100000', 'Capital social',                                    '1', 'TIERS',     'MIXTE'),
    ('10110000', 'Capital souscrit non appelé',                       '1', 'TIERS',     'MIXTE'),
    ('10120000', 'Capital souscrit, appelé, non versé',               '1', 'TIERS',     'MIXTE'),
    ('10130000', 'Capital souscrit, appelé, versé',                   '1', 'TIERS',     'MIXTE'),
    ('10400000', 'Primes liées au capital',                           '1', 'TIERS',     'MIXTE'),
    ('10500000', 'Écarts de réévaluation',                            '1', 'TIERS',     'MIXTE'),
    ('11100000', 'Réserves légales',                                  '1', 'TIERS',     'MIXTE'),
    ('11200000', 'Réserves statutaires',                              '1', 'TIERS',     'MIXTE'),
    ('11800000', 'Autres réserves',                                   '1', 'TIERS',     'MIXTE'),
    ('12100000', 'Report à nouveau (solde créditeur)',                 '1', 'TIERS',     'MIXTE'),
    ('12900000', 'Report à nouveau (solde débiteur)',                  '1', 'TIERS',     'MIXTE'),
    ('13100000', 'Résultat net de l\'exercice (bénéfice)',            '1', 'PRODUIT',   'ENTREE'),
    ('13900000', 'Résultat net de l\'exercice (perte)',               '1', 'CHARGE',    'SORTIE'),
    ('15100000', 'Provisions pour litiges',                           '1', 'TIERS',     'MIXTE'),
    ('15200000', 'Provisions pour garanties données aux clients',     '1', 'TIERS',     'MIXTE'),
    ('15900000', 'Autres provisions pour risques et charges',         '1', 'TIERS',     'MIXTE'),
    ('16100000', 'Emprunts obligataires',                             '1', 'TIERS',     'MIXTE'),
    ('16200000', 'Emprunts auprès des établissements de crédit',      '1', 'TIERS',     'MIXTE'),
    ('16400000', 'Avances reçues de l\'État',                        '1', 'TIERS',     'MIXTE'),
    ('16500000', 'Avances reçues des collectivités locales',          '1', 'TIERS',     'MIXTE'),
    ('16600000', 'Dépôts et cautionnements reçus',                   '1', 'TIERS',     'MIXTE'),
    ('17100000', 'Dettes de crédit-bail et contrats assimilés',       '1', 'TIERS',     'MIXTE'),
    ('18100000', 'Dettes rattachées à des participations',            '1', 'TIERS',     'MIXTE'),
    ('18200000', 'Comptes courants bloqués',                          '1', 'TIERS',     'MIXTE'),

    # ── CLASSE 2 — Comptes d'actif immobilisé ───────────────────────────────
    ('20100000', 'Frais d\'établissement',                           '2', 'TIERS',     'SORTIE'),
    ('20200000', 'Frais de recherche et de développement',            '2', 'TIERS',     'SORTIE'),
    ('20300000', 'Logiciels',                                         '2', 'TIERS',     'SORTIE'),
    ('20400000', 'Brevets, licences, marques',                        '2', 'TIERS',     'SORTIE'),
    ('20500000', 'Fonds commercial',                                  '2', 'TIERS',     'SORTIE'),
    ('20600000', 'Droit au bail',                                     '2', 'TIERS',     'SORTIE'),
    ('21100000', 'Terrains nus',                                      '2', 'TIERS',     'SORTIE'),
    ('21200000', 'Terrains aménagés',                                 '2', 'TIERS',     'SORTIE'),
    ('21300000', 'Bâtiments sur sol propre',                          '2', 'TIERS',     'SORTIE'),
    ('21400000', 'Bâtiments sur sol d\'autrui',                      '2', 'TIERS',     'SORTIE'),
    ('21500000', 'Installations, agencements, aménagements',          '2', 'TIERS',     'SORTIE'),
    ('21600000', 'Matériel et outillage industriel',                  '2', 'TIERS',     'SORTIE'),
    ('21700000', 'Matériel de transport',                             '2', 'TIERS',     'SORTIE'),
    ('21800000', 'Matériel et mobilier de bureau',                    '2', 'TIERS',     'SORTIE'),
    ('21810000', 'Matériel informatique',                             '2', 'TIERS',     'SORTIE'),
    ('21820000', 'Mobilier et agencement de bureau',                  '2', 'TIERS',     'SORTIE'),
    ('21900000', 'Autres immobilisations corporelles',                '2', 'TIERS',     'SORTIE'),
    ('22100000', 'Terrains en crédit-bail',                           '2', 'TIERS',     'SORTIE'),
    ('22300000', 'Bâtiments en crédit-bail',                          '2', 'TIERS',     'SORTIE'),
    ('22600000', 'Matériel en crédit-bail',                           '2', 'TIERS',     'SORTIE'),
    ('23100000', 'Immobilisations corporelles en cours',              '2', 'TIERS',     'SORTIE'),
    ('23200000', 'Immobilisations incorporelles en cours',            '2', 'TIERS',     'SORTIE'),
    ('24100000', 'Titres de participation',                           '2', 'TIERS',     'MIXTE'),
    ('24500000', 'Autres immobilisations financières',                '2', 'TIERS',     'MIXTE'),
    ('24600000', 'Prêts et créances sur associés',                    '2', 'TIERS',     'MIXTE'),
    ('24700000', 'Dépôts et cautionnements versés',                   '2', 'TIERS',     'SORTIE'),
    ('28100000', 'Amortissements des immobilisations incorporelles',  '2', 'CHARGE',    'SORTIE'),
    ('28130000', 'Amortissements des bâtiments',                      '2', 'CHARGE',    'SORTIE'),
    ('28160000', 'Amortissements du matériel et outillage',           '2', 'CHARGE',    'SORTIE'),
    ('28170000', 'Amortissements du matériel de transport',           '2', 'CHARGE',    'SORTIE'),
    ('28180000', 'Amortissements du matériel de bureau',              '2', 'CHARGE',    'SORTIE'),
    ('28181000', 'Amortissements du matériel informatique',           '2', 'CHARGE',    'SORTIE'),

    # ── CLASSE 3 — Comptes de stocks ────────────────────────────────────────
    ('31000000', 'Marchandises',                                      '3', 'TIERS',     'MIXTE'),
    ('32000000', 'Matières premières',                                '3', 'TIERS',     'MIXTE'),
    ('33000000', 'Autres approvisionnements',                         '3', 'TIERS',     'MIXTE'),
    ('34000000', 'Produits en cours',                                 '3', 'TIERS',     'MIXTE'),
    ('35000000', 'Produits finis',                                    '3', 'TIERS',     'MIXTE'),
    ('36000000', 'Produits intermédiaires et résiduels',              '3', 'TIERS',     'MIXTE'),
    ('37000000', 'Stocks en cours de route, en consignation',         '3', 'TIERS',     'MIXTE'),
    ('38000000', 'Achats en cours',                                   '3', 'TIERS',     'MIXTE'),
    ('39100000', 'Dépréciation des stocks de marchandises',           '3', 'CHARGE',    'SORTIE'),

    # ── CLASSE 4 — Comptes de tiers ─────────────────────────────────────────
    ('40100000', 'Fournisseurs',                                      '4', 'TIERS',     'MIXTE'),
    ('40110000', 'Fournisseurs de services',                          '4', 'TIERS',     'MIXTE'),
    ('40200000', 'Fournisseurs - Effets à payer',                     '4', 'TIERS',     'MIXTE'),
    ('40800000', 'Fournisseurs - Factures non parvenues',             '4', 'TIERS',     'MIXTE'),
    ('40900000', 'Fournisseurs débiteurs (avances et acomptes)',      '4', 'TIERS',     'MIXTE'),
    ('41100000', 'Clients',                                           '4', 'TIERS',     'MIXTE'),
    ('41110000', 'Clients — Frais de scolarité',                      '4', 'TIERS',     'ENTREE'),
    ('41200000', 'Clients - Effets à recevoir',                       '4', 'TIERS',     'ENTREE'),
    ('41300000', 'Clients - Avances et acomptes reçus',               '4', 'TIERS',     'ENTREE'),
    ('41400000', 'Clients douteux',                                   '4', 'TIERS',     'MIXTE'),
    ('41500000', 'Clients - Produits non encore facturés',            '4', 'TIERS',     'MIXTE'),
    ('42100000', 'Personnel - Avances et acomptes versés',            '4', 'TIERS',     'MIXTE'),
    ('42200000', 'Personnel - Rémunérations dues',                    '4', 'TIERS',     'SORTIE'),
    ('42300000', 'Personnel - Acomptes sur salaires',                 '4', 'TIERS',     'MIXTE'),
    ('42400000', 'Personnel - Oppositions saisies-arrêts',            '4', 'TIERS',     'MIXTE'),
    ('42500000', 'Personnel - Charges sociales dues',                 '4', 'TIERS',     'SORTIE'),
    ('43100000', 'Sécurité sociale et organismes assimilés',          '4', 'TIERS',     'MIXTE'),
    ('43200000', 'Caisses de retraites',                              '4', 'TIERS',     'SORTIE'),
    ('44100000', 'État - Impôts sur les bénéfices',                   '4', 'TIERS',     'SORTIE'),
    ('44200000', 'État - Impôts et taxes recouvrables',               '4', 'TIERS',     'MIXTE'),
    ('44300000', 'État - TVA facturée',                               '4', 'TIERS',     'MIXTE'),
    ('44400000', 'État - TVA due ou crédit de TVA',                   '4', 'TIERS',     'MIXTE'),
    ('44700000', 'État - Impôts retenus à la source',                 '4', 'TIERS',     'SORTIE'),
    ('44800000', 'État - Autres taxes',                               '4', 'TIERS',     'SORTIE'),
    ('45100000', 'Groupe et associés',                                '4', 'TIERS',     'MIXTE'),
    ('46100000', 'Débiteurs divers',                                  '4', 'TIERS',     'ENTREE'),
    ('46200000', 'Créditeurs divers',                                 '4', 'TIERS',     'SORTIE'),
    ('46300000', 'Apporteurs — Opérations sur le capital',            '4', 'TIERS',     'MIXTE'),
    ('47100000', 'Débiteurs et créditeurs divers — Charges à payer',  '4', 'TIERS',     'MIXTE'),
    ('47200000', 'Produits à recevoir',                               '4', 'TIERS',     'MIXTE'),
    ('47300000', 'Charges à payer',                                   '4', 'TIERS',     'MIXTE'),
    ('47400000', 'Produits constatés d\'avance',                     '4', 'TIERS',     'MIXTE'),
    ('47500000', 'Charges constatées d\'avance',                     '4', 'TIERS',     'MIXTE'),
    ('49100000', 'Dépréciation des comptes clients',                  '4', 'CHARGE',    'SORTIE'),

    # ── CLASSE 5 — Comptes de trésorerie ────────────────────────────────────
    ('51100000', 'Valeurs à l\'encaissement — Chèques à encaisser',  '5', 'TRESORERIE','ENTREE'),
    ('51200000', 'Valeurs à l\'encaissement — Effets à l\'encaissement','5','TRESORERIE','ENTREE'),
    ('52100000', 'Banques locales',                                   '5', 'TRESORERIE','MIXTE'),
    ('52110000', 'Banque principale — Compte courant',                '5', 'TRESORERIE','MIXTE'),
    ('52120000', 'Banque secondaire — Compte courant',                '5', 'TRESORERIE','MIXTE'),
    ('52200000', 'Banques sous-régionales et régionales',             '5', 'TRESORERIE','MIXTE'),
    ('52300000', 'Établissements financiers et assimilés',            '5', 'TRESORERIE','MIXTE'),
    ('53100000', 'Chèques postaux (CCP)',                             '5', 'TRESORERIE','MIXTE'),
    ('54100000', 'Trésor public',                                     '5', 'TRESORERIE','MIXTE'),
    ('55100000', 'Virements de fonds internes',                       '5', 'TRESORERIE','MIXTE'),
    ('57100000', 'Caisse principale',                                 '5', 'TRESORERIE','MIXTE'),
    ('57110000', 'Caisse siège principal',                            '5', 'TRESORERIE','MIXTE'),
    ('57120000', 'Caisse agence / antenne',                           '5', 'TRESORERIE','MIXTE'),
    ('57200000', 'Caisse de menues dépenses (petite caisse)',         '5', 'TRESORERIE','SORTIE'),
    ('58100000', 'Virements internes',                                '5', 'TRESORERIE','MIXTE'),
    ('59100000', 'Dépréciation des valeurs mobilières de placement',  '5', 'CHARGE',    'SORTIE'),

    # ── CLASSE 6 — Comptes de charges ───────────────────────────────────────
    # Achats
    ('60100000', 'Achats de marchandises',                            '6', 'CHARGE',    'SORTIE'),
    ('60200000', 'Achats de matières premières',                      '6', 'CHARGE',    'SORTIE'),
    ('60400000', 'Achats de matières et fournitures consommables',    '6', 'CHARGE',    'SORTIE'),
    ('60410000', 'Fournitures de bureau et papeterie',                '6', 'CHARGE',    'SORTIE'),
    ('60420000', 'Fournitures informatiques',                         '6', 'CHARGE',    'SORTIE'),
    ('60430000', 'Fournitures pédagogiques',                          '6', 'CHARGE',    'SORTIE'),
    ('60500000', 'Autres achats',                                     '6', 'CHARGE',    'SORTIE'),
    ('60800000', 'Achats d\'emballages',                             '6', 'CHARGE',    'SORTIE'),
    # Transports
    ('61100000', 'Transport sur achats',                              '6', 'CHARGE',    'SORTIE'),
    ('61200000', 'Transports sur ventes',                             '6', 'CHARGE',    'SORTIE'),
    ('61300000', 'Transports pour le compte de tiers',                '6', 'CHARGE',    'SORTIE'),
    ('61400000', 'Transports du personnel',                           '6', 'CHARGE',    'SORTIE'),
    ('61500000', 'Voyages et déplacements',                           '6', 'CHARGE',    'SORTIE'),
    ('61600000', 'Transport de valeurs',                              '6', 'CHARGE',    'SORTIE'),
    ('61900000', 'Autres charges de transport',                       '6', 'CHARGE',    'SORTIE'),
    # Services extérieurs A
    ('62100000', 'Sous-traitance générale',                           '6', 'CHARGE',    'SORTIE'),
    ('62200000', 'Locations et charges locatives',                    '6', 'CHARGE',    'SORTIE'),
    ('62210000', 'Loyer des locaux',                                  '6', 'CHARGE',    'SORTIE'),
    ('62220000', 'Loyer du matériel',                                 '6', 'CHARGE',    'SORTIE'),
    ('62300000', 'Redevances de crédit-bail',                         '6', 'CHARGE',    'SORTIE'),
    ('62400000', 'Entretien, réparations et maintenance',             '6', 'CHARGE',    'SORTIE'),
    ('62410000', 'Entretien bâtiments et locaux',                     '6', 'CHARGE',    'SORTIE'),
    ('62420000', 'Entretien matériel informatique',                   '6', 'CHARGE',    'SORTIE'),
    ('62430000', 'Entretien et réparations véhicules',                '6', 'CHARGE',    'SORTIE'),
    ('62500000', 'Primes d\'assurances',                             '6', 'CHARGE',    'SORTIE'),
    ('62600000', 'Études, recherches et documentation',               '6', 'CHARGE',    'SORTIE'),
    ('62700000', 'Publicité, publications, relations publiques',       '6', 'CHARGE',    'SORTIE'),
    ('62800000', 'Frais de télécommunication',                        '6', 'CHARGE',    'SORTIE'),
    ('62810000', 'Abonnements téléphoniques',                         '6', 'CHARGE',    'SORTIE'),
    ('62820000', 'Abonnements internet',                              '6', 'CHARGE',    'SORTIE'),
    ('62900000', 'Autres services extérieurs A',                      '6', 'CHARGE',    'SORTIE'),
    # Services extérieurs B
    ('63100000', 'Frais bancaires',                                   '6', 'CHARGE',    'SORTIE'),
    ('63200000', 'Rémunérations d\'intermédiaires et conseils',      '6', 'CHARGE',    'SORTIE'),
    ('63300000', 'Frais de formation du personnel',                   '6', 'CHARGE',    'SORTIE'),
    ('63400000', 'Frais de recrutement du personnel',                 '6', 'CHARGE',    'SORTIE'),
    ('63500000', 'Frais de gardiennage et sécurité',                  '6', 'CHARGE',    'SORTIE'),
    ('63600000', 'Frais postaux',                                     '6', 'CHARGE',    'SORTIE'),
    ('63700000', 'Cotisations et abonnements professionnels',         '6', 'CHARGE',    'SORTIE'),
    ('63800000', 'Frais de réception et représentation',              '6', 'CHARGE',    'SORTIE'),
    ('63900000', 'Autres services extérieurs B',                      '6', 'CHARGE',    'SORTIE'),
    # Impôts et taxes
    ('64100000', 'Impôts fonciers et taxes assimilées',               '6', 'CHARGE',    'SORTIE'),
    ('64200000', 'Droits d\'enregistrement et de timbre',            '6', 'CHARGE',    'SORTIE'),
    ('64400000', 'Taxes sur le chiffre d\'affaires non récupérables', '6', 'CHARGE',    'SORTIE'),
    ('64500000', 'Taxes sur les véhicules',                           '6', 'CHARGE',    'SORTIE'),
    ('64600000', 'Droits de douane',                                  '6', 'CHARGE',    'SORTIE'),
    ('64700000', 'Taxes sur les salaires',                            '6', 'CHARGE',    'SORTIE'),
    ('64800000', 'Autres impôts et taxes',                            '6', 'CHARGE',    'SORTIE'),
    # Charges de personnel
    ('66100000', 'Rémunérations directes versées au personnel national','6','CHARGE',   'SORTIE'),
    ('66110000', 'Salaires du personnel administratif',               '6', 'CHARGE',    'SORTIE'),
    ('66120000', 'Salaires du personnel enseignant',                  '6', 'CHARGE',    'SORTIE'),
    ('66130000', 'Salaires du personnel d\'entretien',               '6', 'CHARGE',    'SORTIE'),
    ('66200000', 'Rémunérations directes versées au personnel non national','6','CHARGE','SORTIE'),
    ('66300000', 'Indemnités forfaitaires versées au personnel',      '6', 'CHARGE',    'SORTIE'),
    ('66310000', 'Indemnités de transport',                           '6', 'CHARGE',    'SORTIE'),
    ('66320000', 'Indemnités de logement',                            '6', 'CHARGE',    'SORTIE'),
    ('66400000', 'Charges sociales — IPRES (retraite)',               '6', 'CHARGE',    'SORTIE'),
    ('66410000', 'Charges sociales — CSS (sécurité sociale)',         '6', 'CHARGE',    'SORTIE'),
    ('66500000', 'Charges sociales — Assurances accidents du travail','6', 'CHARGE',    'SORTIE'),
    ('66600000', 'Charges de retraite complémentaire',                '6', 'CHARGE',    'SORTIE'),
    ('66700000', 'Charges sociales diverses',                         '6', 'CHARGE',    'SORTIE'),
    ('66800000', 'Autres charges de personnel',                       '6', 'CHARGE',    'SORTIE'),
    ('66900000', 'Participations des travailleurs',                   '6', 'CHARGE',    'SORTIE'),
    # Charges financières
    ('67100000', 'Intérêts des emprunts',                             '6', 'CHARGE',    'SORTIE'),
    ('67200000', 'Intérêts des dettes de crédit-bail',               '6', 'CHARGE',    'SORTIE'),
    ('67300000', 'Escomptes accordés',                                '6', 'CHARGE',    'SORTIE'),
    ('67400000', 'Pertes sur créances irrécouvrables',                '6', 'CHARGE',    'SORTIE'),
    ('67500000', 'Différences négatives de change',                   '6', 'CHARGE',    'SORTIE'),
    ('67800000', 'Autres charges financières',                        '6', 'CHARGE',    'SORTIE'),
    # Dotations aux amortissements et provisions
    ('68100000', 'Dotations aux amortissements des immobilisations incorporelles','6','CHARGE','SORTIE'),
    ('68110000', 'Dotations aux amortissements des immobilisations corporelles','6','CHARGE','SORTIE'),
    ('68120000', 'Dotations aux provisions pour dépréciation des immobilisations','6','CHARGE','SORTIE'),
    ('68200000', 'Dotations aux provisions pour dépréciation des stocks','6','CHARGE','SORTIE'),
    ('68300000', 'Dotations aux provisions pour dépréciation des créances','6','CHARGE','SORTIE'),
    ('68900000', 'Dotations aux provisions pour risques et charges',  '6', 'CHARGE',    'SORTIE'),
    # Impôts sur bénéfices
    ('69100000', 'Impôts sur le résultat',                            '6', 'CHARGE',    'SORTIE'),
    ('69200000', 'Impôts sur les sociétés',                           '6', 'CHARGE',    'SORTIE'),
    ('69400000', 'Contribution forfaitaire',                          '6', 'CHARGE',    'SORTIE'),

    # ── CLASSE 7 — Comptes de produits ──────────────────────────────────────
    # Ventes
    ('70100000', 'Ventes de marchandises',                            '7', 'PRODUIT',   'ENTREE'),
    ('70200000', 'Ventes de produits finis',                          '7', 'PRODUIT',   'ENTREE'),
    ('70400000', 'Travaux, études et prestations de services',        '7', 'PRODUIT',   'ENTREE'),
    ('70410000', 'Frais de scolarité — Licence',                      '7', 'PRODUIT',   'ENTREE'),
    ('70420000', 'Frais de scolarité — Master',                       '7', 'PRODUIT',   'ENTREE'),
    ('70430000', 'Frais de scolarité — BTS / DUT',                    '7', 'PRODUIT',   'ENTREE'),
    ('70440000', 'Frais de scolarité — Doctorat',                     '7', 'PRODUIT',   'ENTREE'),
    ('70500000', 'Études et prestations diverses',                    '7', 'PRODUIT',   'ENTREE'),
    ('70600000', 'Produits des activités annexes',                    '7', 'PRODUIT',   'ENTREE'),
    ('70610000', 'Inscriptions et droits d\'examen',                 '7', 'PRODUIT',   'ENTREE'),
    ('70620000', 'Location de salles et équipements',                 '7', 'PRODUIT',   'ENTREE'),
    ('70630000', 'Formation continue et professionnelle',             '7', 'PRODUIT',   'ENTREE'),
    ('70700000', 'Produits accessoires',                              '7', 'PRODUIT',   'ENTREE'),
    # Autres produits d'exploitation
    ('72100000', 'Production immobilisée — Immobilisations incorporelles','7','PRODUIT','ENTREE'),
    ('72200000', 'Production immobilisée — Immobilisations corporelles','7','PRODUIT',  'ENTREE'),
    ('73100000', 'Variations des stocks de produits finis',           '7', 'PRODUIT',   'MIXTE'),
    # Subventions
    ('74100000', 'Subventions d\'exploitation reçues',               '7', 'PRODUIT',   'ENTREE'),
    ('74200000', 'Subventions d\'équilibre reçues',                  '7', 'PRODUIT',   'ENTREE'),
    ('74300000', 'Subventions d\'investissement virées au résultat',  '7', 'PRODUIT',   'ENTREE'),
    # Produits financiers
    ('75100000', 'Revenus des participations',                        '7', 'PRODUIT',   'ENTREE'),
    ('75200000', 'Revenus des créances',                              '7', 'PRODUIT',   'ENTREE'),
    ('75300000', 'Revenus des valeurs mobilières de placement',       '7', 'PRODUIT',   'ENTREE'),
    ('75400000', 'Intérêts de prêts accordés',                        '7', 'PRODUIT',   'ENTREE'),
    ('75500000', 'Escomptes obtenus',                                 '7', 'PRODUIT',   'ENTREE'),
    ('75600000', 'Gains de change',                                   '7', 'PRODUIT',   'ENTREE'),
    ('75800000', 'Autres produits financiers',                        '7', 'PRODUIT',   'ENTREE'),
    # Reprises sur provisions
    ('78100000', 'Reprises sur amortissements des immobilisations',   '7', 'PRODUIT',   'ENTREE'),
    ('78200000', 'Reprises sur provisions pour dépréciation stocks',  '7', 'PRODUIT',   'ENTREE'),
    ('78300000', 'Reprises sur provisions pour dépréciation créances','7', 'PRODUIT',   'ENTREE'),
    ('78900000', 'Reprises sur provisions pour risques et charges',   '7', 'PRODUIT',   'ENTREE'),
    ('79100000', 'Transferts de charges d\'exploitation',            '7', 'PRODUIT',   'ENTREE'),
    ('79200000', 'Transferts de charges financières',                 '7', 'PRODUIT',   'ENTREE'),

    # ── CLASSE 8 — Autres charges et produits (HAO) ─────────────────────────
    ('81000000', 'Valeurs comptables des cessions d\'immobilisations','8','CHARGE',    'SORTIE'),
    ('81100000', 'Valeurs comptables des cessions d\'immobilisations incorporelles','8','CHARGE','SORTIE'),
    ('81200000', 'Valeurs comptables des cessions d\'immobilisations corporelles','8','CHARGE','SORTIE'),
    ('81300000', 'Valeurs comptables des cessions d\'immobilisations financières','8','CHARGE','SORTIE'),
    ('82000000', 'Produits des cessions d\'immobilisations',         '8', 'PRODUIT',   'ENTREE'),
    ('82100000', 'Produits des cessions d\'immobilisations incorporelles','8','PRODUIT','ENTREE'),
    ('82200000', 'Produits des cessions d\'immobilisations corporelles','8','PRODUIT',  'ENTREE'),
    ('82300000', 'Produits des cessions d\'immobilisations financières','8','PRODUIT', 'ENTREE'),
    ('83000000', 'Charges HAO diverses',                              '8', 'CHARGE',    'SORTIE'),
    ('83100000', 'Charges HAO liées aux restructurations',            '8', 'CHARGE',    'SORTIE'),
    ('83200000', 'Charges HAO liées aux catastrophes et sinistres',   '8', 'CHARGE',    'SORTIE'),
    ('83900000', 'Autres charges HAO',                                '8', 'CHARGE',    'SORTIE'),
    ('84000000', 'Produits HAO divers',                               '8', 'PRODUIT',   'ENTREE'),
    ('84100000', 'Produits HAO liés aux restructurations',            '8', 'PRODUIT',   'ENTREE'),
    ('84200000', 'Subventions HAO reçues',                            '8', 'PRODUIT',   'ENTREE'),
    ('84900000', 'Autres produits HAO',                               '8', 'PRODUIT',   'ENTREE'),
    ('85000000', 'Dotations HAO',                                     '8', 'CHARGE',    'SORTIE'),
    ('85100000', 'Dotations HAO aux provisions',                      '8', 'CHARGE',    'SORTIE'),
    ('86000000', 'Reprises HAO',                                      '8', 'PRODUIT',   'ENTREE'),
    ('86100000', 'Reprises HAO sur provisions',                       '8', 'PRODUIT',   'ENTREE'),
    ('88000000', 'Subventions d\'équilibre',                         '8', 'PRODUIT',   'ENTREE'),
    ('89000000', 'Impôts sur le résultat HAO',                        '8', 'CHARGE',    'SORTIE'),

    # ── Comptes utilitaires pour catégories de dépense caisse ──────────────
    ('64000000', 'Impôts et taxes divers',                            '6', 'CHARGE',    'SORTIE'),
    ('65800000', 'Charges diverses et exceptionnelles',               '6', 'CHARGE',    'SORTIE'),
    ('67000000', 'Charges financières diverses',                      '6', 'CHARGE',    'SORTIE'),
]

# Catégorie de dépense caisse associée à chaque matricule
# Correspond à CaisseMovement.CATEGORIE_COMPTE_MATRICULE (sens inverse)
CATEGORIE_PAR_MATRICULE = {
    '60410000': 'FOURNITURES_BUREAU',
    '60420000': 'FOURNITURES_BUREAU',
    '62200000': 'LOYER',
    '62210000': 'LOYER',
    '62410000': 'ENTRETIEN',
    '62500000': 'ASSURANCE',
    '62700000': 'PUBLICITE_COMM',
    '62800000': 'TELEPHONE',
    '62810000': 'TELEPHONE',
    '62820000': 'INTERNET',
    '63100000': 'FRAIS_BANCAIRES',
    '63200000': 'HONORAIRES',
    '63300000': 'FORMATION_PERSONNEL',
    '63400000': 'FRAIS_POSTAUX',
    '63500000': 'GARDIENNAGE_SECURITE',
    '63600000': 'FRAIS_POSTAUX',
    '63800000': 'RECEPTIONS',
    '64000000': 'IMPOTS_TAXES',
    '64100000': 'IMPOTS_TAXES',
    '64200000': 'IMPOTS_TAXES',
    '64700000': 'IMPOTS_TAXES',
    '64800000': 'IMPOTS_TAXES',
    '65800000': 'AUTRE',
    '66100000': 'SALAIRES',
    '66110000': 'SALAIRES',
    '66120000': 'SALAIRES',
    '66130000': 'SALAIRES',
    '66300000': 'SALAIRES',
    '66310000': 'DEPLACEMENTS',
    '66400000': 'CHARGES_SOCIALES',
    '66410000': 'CHARGES_SOCIALES',
    '66500000': 'CHARGES_SOCIALES',
    '66600000': 'CHARGES_SOCIALES',
    '67000000': 'INTERETS_BANCAIRES',
    '67100000': 'INTERETS_BANCAIRES',
    '61500000': 'DEPLACEMENTS',
}


class Command(BaseCommand):
    help = 'Insère le plan comptable SYSCOHADA révisé complet dans toutes les bases tenant'

    def add_arguments(self, parser):
        parser.add_argument(
            '--reset',
            action='store_true',
            help='Réinitialise tous les comptes (supprime et recrée) avant insertion',
        )
        parser.add_argument(
            '--database',
            default=None,
            help='Alias de base spécifique (ex: db_rytal_isi). Par défaut : toutes les bases tenant.',
        )

    def handle(self, *args, **options):
        from django.conf import settings
        from academic_core.db_router import TENANT_ONLY_APP_LABELS

        # Déterminer les bases cibles
        all_dbs = list(settings.DATABASES.keys())
        if options['database']:
            target_dbs = [options['database']]
        else:
            # Toutes les bases non-default
            target_dbs = [db for db in all_dbs if db != 'default']

        if not target_dbs:
            self.stdout.write(self.style.WARNING('Aucune base tenant trouvée.'))
            return

        for db_alias in target_dbs:
            self.stdout.write(f'\n--- Base : {db_alias} ---')
            self._populate_db(db_alias, options['reset'])

    @transaction.atomic
    def _populate_db(self, db_alias, reset):
        from academic_core.apps.accounting.models import CompteComptable

        qs = CompteComptable.objects.using(db_alias)

        if reset:
            count = qs.count()
            qs.all().delete()
            self.stdout.write(self.style.WARNING(f'  {count} compte(s) supprimé(s).'))

        created = 0
        skipped = 0
        updated_cat = 0

        for matricule, libelle, classe, nature, sens in COMPTES:
            categorie = CATEGORIE_PAR_MATRICULE.get(matricule, '')
            try:
                obj, was_created = qs.get_or_create(
                    matricule=matricule,
                    defaults={
                        'libelle':   libelle,
                        'classe':    classe,
                        'nature':    nature,
                        'sens':      sens,
                        'categorie': categorie,
                        'is_active': False,
                    }
                )
            except Exception as e:
                self.stdout.write(self.style.ERROR(f'  Erreur {matricule}: {e}'))
                continue

            if was_created:
                created += 1
            else:
                skipped += 1
                if categorie and not obj.categorie:
                    obj.categorie = categorie
                    obj.save(using=db_alias, update_fields=['categorie'])
                    updated_cat += 1

        # Post-traitement : forcer la catégorie sur les comptes déjà présents
        for mat, cat in CATEGORIE_PAR_MATRICULE.items():
            nb = qs.filter(matricule=mat, categorie='').update(categorie=cat)
            updated_cat += nb

        self.stdout.write(self.style.SUCCESS(
            f'  OK {created} créé(s)  —  {skipped} ignoré(s)  '
            f'  MAJ {updated_cat} catégorie(s) màj  '
            f'  [{len(COMPTES)} comptes définis]'
        ))
