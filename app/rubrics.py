"""Official LVA/LVB attestation grids ("Grilles d'évaluation pour attestation en
langues vivantes") + legacy generic presets.

Attestation model
-----------------
Each attestation rubric has 4 criteria. The model assigns ONE CEFR level per
criterion (with verbatim evidence). Points per level (official grid scale):
    A1=1, A2=3, B1=5, B2=10, C1=20, C2=30   -> total /120
The attestation is read off the official score thresholds, which DIFFER by
modality (from the PDF's "TABLEAU DE CONVERSION" headers):
    comprehension : A1>=3, A2>=9, B1>=15, B2>=30, C1>=60, C2>=90
    expression    : A1>=4, A2>=12, B1>=20, B2>=40, C1>=80, C2=120

The separate "/20 note bands" per (classe, LVA/LVB) are a manual teacher
reference (see NOTE_BANDS) — the app never auto-grades off them; attestation
is always computed from the /120 score against the official thresholds.
"""

# ---------------------------------------------------------------- point scale
LEVEL_POINTS = {"A1": 1, "A2": 3, "B1": 5, "B2": 10, "C1": 20, "C2": 30}
SCORE_MAX = 120
CEFR_ORDER = ("A1", "A2", "B1", "B2", "C1", "C2")

# Official score thresholds (score out of 120 -> attestation)
SCORE_THRESHOLDS = {
    "comprehension": {"A1": 3, "A2": 9, "B1": 15, "B2": 30, "C1": 60, "C2": 90},
    "expression":    {"A1": 4, "A2": 12, "B1": 20, "B2": 40, "C1": 80, "C2": 120},
}


def attestation_from_score(score: int, modalite: str) -> str:
    """/120 score -> attestation CEFR level using the official thresholds."""
    th = SCORE_THRESHOLDS[modalite]
    for lvl in reversed(CEFR_ORDER):
        if score >= th[lvl]:
            return lvl
    return "—"  # below the official A1 floor


def normalize_cefr(token: str) -> str | None:
    """'B1+' / 'B2-' / 'B1 / B2 visé' -> the nearest canonical CEFR level (or None)."""
    t = (token or "").strip().upper().replace("É", "E")
    for lvl in CEFR_ORDER:
        if t == lvl:
            return lvl
    # 'B1+' -> B1 ; 'B2-' -> B2 ; 'B1/B2' -> B1 (lower bound dominates a band)
    core = t.split("/")[0].strip()
    core = core.lstrip("0123456789+- ").strip()
    for lvl in CEFR_ORDER:
        if core.startswith(lvl):
            # '+': stays at that level ; '-': stays at that level (floor)
            return lvl
    return None


# ---------------------------------------------------------------- the grids
# Each criterion may carry `gaps`: short (2-3 word) level-to-level difference
# summaries used by the "Mode Évaluation" UI (the chip next to each side level).
# Keyed on the CENTRE level L:
#   up   = what L+1 adds above L  (right side chip, "what you gain going up")
#   down = what L adds above L-1  (left side chip, "what you miss below")
_COMP_CRITERIA = [
    {"name": "Identification du contexte / situation d'énonciation",
     "description": ("C2: comprend sans difficulté, à de rares exceptions près, les éléments relatifs au "
        "contexte et à la situation d'énonciation. C1: identifie les détails fins ou l'implicite tout en les "
        "replaçant dans le contexte. B2: identifie la richesse d'un contexte ou d'une situation, y compris en "
        "relevant des éléments implicites. B1: relève des informations détaillées sur le contexte (objet, "
        "enjeux, perspective narrative, expériences) et établit des liens entre elles. A2: relève des "
        "informations explicites sur le contexte (thème, lieux, personnes, événements). A1: relève des "
        "informations isolées simples et les articule en partie les unes aux autres."),
     "gaps": {"A1": {"up": "infos explicites"},
              "A2": {"up": "détail + liens", "down": "infos isolées simples"},
              "B1": {"up": "richesse, implicite", "down": "détail, liens"},
              "B2": {"up": "détails fins replacés", "down": "richesse, implicites"},
              "C1": {"up": "compréhension aisée", "down": "détails fins"},
              "C2": {"down": "avec quelques difficultés"}}},
    {"name": "Identification des réseaux de sens",
     "description": ("C2: comprend sans difficulté, à de rares exceptions près, les réseaux de sens. "
        "C1: identifie et analyse la logique interne d'un document ou dossier en distinguant le cas échéant "
        "la digression. B2: identifie la cohérence globale d'un document ou dossier : principales raisons "
        "pour/contre, reconstitue une chronologie, repère des ruptures chronologiques. B1: relève "
        "l'essentiel des éléments porteurs de sens : plan général du texte, liens de causalité simples. "
        "A2: comprend globalement : sujet principal, regroupement de termes d'un même champ lexical. "
        "A1: construit une amorce de compréhension en relevant des mots ou expressions."),
     "gaps": {"A1": {"up": "sujet + champs lexicaux"},
              "A2": {"up": "plan + causalités", "down": "amorce de compréhension"},
              "B1": {"up": "cohérence globale", "down": "plan, causalités"},
              "B2": {"up": "logique interne", "down": "cohérence globale"},
              "C1": {"up": "compréhension aisée", "down": "logique interne"},
              "C2": {"down": "avec quelques difficultés"}}},
    {"name": "Identification des stratégies de communication",
     "description": ("C2: comprend sans difficulté, à de rares exceptions près, les stratégies de "
        "communication. C1: identifie l'articulation de documents ; la tonalité d'un propos (ironie, humour, "
        "stratégies interpersonnelles). B2: repère une intention en distinguant l'expression d'un point de "
        "vue de l'exposé de faits ; identifie des éléments implicites de l'articulation inter-documentaire. "
        "B1: identifie l'expression de points de vue, souhaits et/ou perspectives ; la nature de "
        "l'articulation entre documents (lien chronologique, illustratif, d'opposition). A2: identifie la "
        "nature du/des documents et la met en lien avec quelques éléments du contenu. A1: relève quelques "
        "données ou caractéristiques évidentes d'un document (dates, titres, paragraphes)."),
     "gaps": {"A1": {"up": "documents identifiés"},
              "A2": {"up": "points de vue, liens", "down": "caractéristiques évidentes"},
              "B1": {"up": "intention, implicite", "down": "points de vue"},
              "B2": {"up": "articulation, tonalité", "down": "intention, implicites"},
              "C1": {"up": "compréhension aisée", "down": "articulation, tonalité"},
              "C2": {"down": "avec quelques difficultés"}}},
]

_ECRITE_CRITERIA = [
    {"name": "Qualité du contenu",
     "description": ("C2: rend de fines nuances de sens en rapport avec un sujet complexe. C1: traite le "
        "sujet et produit un écrit fluide et convaincant, étayé par des éléments (inter)culturels pertinents. "
        "B2: produit un écrit clair, détaillé et globalement efficace, y compris en s'appuyant sur certains "
        "éléments (inter)culturels. B1: écrit intelligible et relativement développé, référence à quelques "
        "éléments (inter)culturels. A2: traite le sujet, même si la production est courte. A1: amorce "
        "simplement une production écrite en lien avec le sujet."),
     "gaps": {"A1": {"up": "traite le sujet"},
              "A2": {"up": "la développe", "down": "n'amorce que"},
              "B1": {"up": "détaillé, efficace", "down": "court, ref minime"},
              "B2": {"up": "fluide, convaincant", "down": "moins détaillé"},
              "C1": {"up": "fines nuances", "down": "moins convaincant"},
              "C2": {"down": "sans fines nuances"}}},
    {"name": "Cohérence dans la construction du discours",
     "description": ("C2: produit un discours cohérent et construit sur un sujet complexe. C1: récit ou "
        "argumentation complexe avec un usage maîtrisé des moyens linguistiques de structuration et "
        "d'articulation. B2: récit ou argumentation indiquant la relation entre les faits et les idées dans "
        "un texte bien structuré. B1: rend compte d'expériences en décrivant ses sentiments et réactions ; "
        "expose et illustre un point de vue ; raconte une histoire de manière cohérente. A2: expose une "
        "expérience ou un point de vue en utilisant des connecteurs élémentaires. A1: énumère des "
        "informations sur soi-même ou les autres."),
     "gaps": {"A1": {"up": "articule les expériences"},
              "A2": {"up": "décris tes sentiments", "down": "n'énumère que"},
              "B1": {"up": "bien structurée", "down": "connecteurs élémentaires"},
              "B2": {"up": "structure complexe", "down": "moins structurée"},
              "C1": {"up": "sujets complexes", "down": "structure simple"},
              "C2": {"down": "sujets moins complexes"}}},
    {"name": "Correction de la langue écrite",
     "description": ("C2: très haut degré de correction grammaticale, y compris structures complexes sur un "
        "sujet complexe. C1: haut degré de correction maintenu tout au long de la rédaction, y compris "
        "structures complexes. B2: bonne maîtrise des structures simples et courantes ; les erreurs sur les "
        "structures complexes ne donnent pas lieu à des malentendus. B1: bonne maîtrise des structures "
        "simples et courantes ; les erreurs sur les structures simples ne gênent pas la lecture. A2: texte "
        "immédiatement compréhensible malgré des erreurs fréquentes. A1: texte globalement compréhensible "
        "mais dont la lecture est peu aisée."),
     "gaps": {"A1": {"up": "compréhensible malgré erreurs"},
              "A2": {"up": "structures simples maîtrisées", "down": "structures par cœur"},
              "B1": {"up": "pas de malentendu", "down": "erreurs fréquentes"},
              "B2": {"up": "correction soutenue", "down": "erreurs tolérées"},
              "C1": {"up": "très haut degré", "down": "erreurs complexes subsistent"},
              "C2": {"down": "degré moindre"}}},
    {"name": "Richesse de la langue",
     "description": ("C2: très vaste répertoire lexical pertinent incluant expressions idiomatiques, nuances "
        "de formulation et structures variées même sur un sujet complexe. C1: vaste répertoire pertinent "
        "incluant expressions idiomatiques, nuances de formulation et structures variées. B2: étendue du "
        "lexique et des structures suffisante pour permettre précision et variété des formulations. B1: "
        "étendue lexicale relative nécessitant l'usage de périphrases et de répétitions. A2: mots adaptés à "
        "l'intention de communication, en dépit d'un répertoire lexical limité. A1: texte intelligible "
        "malgré un lexique très limité."),
     "gaps": {"A1": {"up": "vocabulaire du quotidien"},
              "A2": {"up": "une marge se crée", "down": "lexique par cœur"},
              "B1": {"up": "nuances, registre soutenu", "down": "limité, répétitif"},
              "B2": {"up": "riche, idiomatique", "down": "correct mais limité"},
              "C1": {"up": "maîtrise extrême", "down": "moins de nuances"},
              "C2": {"down": "moins de spontanéité"}}},
]

_ORAL_CRITERIA = [
    {"name": "Expression orale en continu",
     "description": ("C2: rend de fines nuances de sens en rapport avec un sujet complexe. C1: développe une "
        "argumentation complexe fondée sur des aspects (inter)culturels, de manière synthétique et fluide, "
        "tout en s'assurant de sa bonne réception. B2: développe un point de vue pertinent et étayé, y "
        "compris par des reformulations qui ne rompent pas le fil du discours ; nuance en s'appuyant sur des "
        "références (inter)culturelles. B1: expose un point de vue de manière simple, illustré par des "
        "exemples et des références à des aspects (inter)culturels ; discours structuré (relations de "
        "causalité, comparaisons). A2: exprime un avis en termes simples ; discours bref, éléments "
        "juxtaposés. A1: exprime un avis en termes très simples ; énoncés ponctués de pauses, hésitations "
        "et faux démarrages."),
     "gaps": {"A1": {"up": "avis en termes simples"},
              "A2": {"up": "point de vue illustré", "down": "avis en termes simples"},
              "B1": {"up": "étayé, nuancé", "down": "simple, illustré"},
              "B2": {"up": "argumentation complexe", "down": "moins étayé"},
              "C1": {"up": "fines nuances", "down": "argumentation moins complexe"},
              "C2": {"down": "sans fines nuances"}}},
    {"name": "Interaction orale",
     "description": ("C2: interagit avec aisance et spontanéité, contribue habilement à la construction de "
        "l'échange, y compris en exploitant des références (inter)culturelles sur un sujet complexe. C1: "
        "interagit avec aisance et contribue habilement, y compris références (inter)culturelles. B2: "
        "argumente et cherche à convaincre ; réagit avec pertinence et relance la discussion, y compris "
        "pour amener l'échange sur un terrain familier ou (inter)culturel. B1: engage, soutient et clore une "
        "conversation simple sur des sujets familiers ; référence à des aspects (inter)culturels. A2: répond "
        "et réagit de manière simple. A1: intervient simplement mais la communication repose sur la "
        "répétition et la reformulation."),
     "gaps": {"A1": {"up": "réagit de manière simple"},
              "A2": {"up": "conversation simple tenue", "down": "réaction simple"},
              "B1": {"up": "argumente, relance", "down": "conversation simple"},
              "B2": {"up": "aisance, habileté", "down": "argumentation moins fine"},
              "C1": {"up": "sujets complexes", "down": "aisance moindre"},
              "C2": {"down": "moins de spontanéité"}}},
    {"name": "Correction de la langue orale",
     "description": ("C2: utilise avec une bonne maîtrise tout l'éventail des traits phonologiques de la "
        "langue cible, toujours intelligible même sur un sujet complexe. C1: assez bonne maîtrise de tout "
        "l'éventail phonologique, toujours intelligible ; les rares erreurs de langue ne donnent pas lieu à "
        "des malentendus. B2: l'accent peut subir l'influence d'autres langues mais n'entrave pas "
        "l'intelligibilité ; les erreurs de langue ne donnent pas lieu à malentendu. B1: s'exprime de "
        "manière intelligible malgré l'influence d'autres langues ; bonne maîtrise des structures simples. "
        "A2: s'exprime de manière suffisamment claire pour être compris, mais la compréhension requiert un "
        "effort des interlocuteurs. A1: utilise un répertoire très limité d'expressions et de mots "
        "mémorisés de façon compréhensible."),
     "gaps": {"A1": {"up": "compris avec effort"},
              "A2": {"up": "intelligible", "down": "effort d'interlocuteurs"},
              "B1": {"up": "pas de malentendu", "down": "intelligibilité seule"},
              "B2": {"up": "rares erreurs", "down": "intelligibilité seule"},
              "C1": {"up": "maîtrise phonologique", "down": "rares erreurs"},
              "C2": {"down": "maîtrise moindre"}}},
    {"name": "Richesse de la langue",
     "description": ("C2: vaste répertoire lexical pertinent incluant expressions idiomatiques, nuances "
        "de formulation et structures variées même sur un sujet complexe. C1: vaste répertoire pertinent "
        "incluant expressions idiomatiques, nuances de formulation et structures variées. B2: discours et "
        "énoncés assez fluides dont l'étendue du lexique est suffisante pour permettre précision et variété "
        "des formulations. B1: étendue lexicale relative nécessitant l'usage de périphrases et répétitions. "
        "A2: mots adaptés à l'intention de communication, en dépit d'un répertoire lexical limité. A1: "
        "énoncés intelligibles malgré un lexique très limité."),
     "gaps": {"A1": {"up": "mots adaptés"},
              "A2": {"up": "étendue lexicale", "down": "lexique très limité"},
              "B1": {"up": "précision, variété", "down": "périphrases, répétitions"},
              "B2": {"up": "vaste répertoire", "down": "précision, variété"},
              "C1": {"up": "sujets complexes", "down": "répertoire moins vaste"},
              "C2": {"down": "moins de nuances"}}},
]


def _mk(rubric_id, name, mode, criteria, modalite, modes=None):
    r = {
        "id": rubric_id,
        "name": name,
        "mode": mode,
        "criteria": criteria,
        "is_preset": True,
        "attestation": True,
        "modalite": modalite,
        "point_scale": dict(LEVEL_POINTS),
    }
    if modes:
        r["modes"] = modes
    return r


ATTES_RUBRICS = [
    _mk("att-comp", "Attestation LVA/LVB — Compréhension (écrit & oral)",
        "written", _COMP_CRITERIA, "comprehension", modes=["written", "oral"]),
    _mk("att-exp-ecrite", "Attestation LVA/LVB — Expression écrite",
        "written", _ECRITE_CRITERIA, "expression"),
    _mk("att-exp-orale", "Attestation LVA/LVB — Expression orale",
        "oral", _ORAL_CRITERIA, "expression"),
]


# ---------------------------------------------------------------- official
# "tableaux de conversion" (note sur 20 -> attestation), teacher reference.
# Band ranges are transcribed verbatim from the official document (the printed
# bands are in "points score" units, same scale as the /120 attestation score;
# the tables also print a "Note sur 20" reference row). `verified=True` = the
# level label is explicitly printed in that band; `verified=False` = level
# derived from the official score thresholds (see NOTE_THRESHOLDS) — cross-check
# against the official document. The app does NOT grade from these bands.
NOTE_BANDS = {
    ("comprehension", "premiere", "LVA"): [
        {"from": 0, "to": 0, "label": None, "verified": True},
        {"from": 1, "to": 5, "label": "A1", "verified": True},
        {"from": 6, "to": 8, "label": "A1", "verified": False},
        {"from": 9, "to": 10, "label": "A2", "verified": True},
        {"from": 11, "to": 12, "label": "A2", "verified": False},
        {"from": 13, "to": 14, "label": "A2", "verified": False},
        {"from": 15, "to": 20, "label": "B1", "verified": True},
        {"from": 21, "to": None, "label": "B2", "verified": False}],  # visé: B1 / B2
    ("comprehension", "premiere", "LVB"): [
        {"from": 0, "to": 0, "label": None, "verified": True},
        {"from": 1, "to": 2, "label": "A1", "verified": False},
        {"from": 3, "to": 4, "label": "A1", "verified": False},
        {"from": 5, "to": 6, "label": "A1", "verified": False},
        {"from": 7, "to": 8, "label": "A1", "verified": False},
        {"from": 9, "to": 9, "label": "A2", "verified": True},
        {"from": 10, "to": 10, "label": "A2", "verified": False},
        {"from": 11, "to": None, "label": "B1", "verified": False}],  # visé: A2 / B1
    ("comprehension", "terminale", "LVA"): [
        {"from": 0, "to": 0, "label": None, "verified": True},
        {"from": 1, "to": 5, "label": "A1", "verified": False},
        {"from": 6, "to": 10, "label": "A2", "verified": False},
        {"from": 11, "to": 14, "label": "A2", "verified": False},
        {"from": 15, "to": 20, "label": "B1", "verified": False},
        {"from": 21, "to": 24, "label": "B1", "verified": False},
        {"from": 25, "to": 29, "label": "B1", "verified": False},
        {"from": 30, "to": None, "label": "B2", "verified": False}],  # visé: B2
    ("comprehension", "terminale", "LVB"): [
        {"from": 0, "to": 0, "label": None, "verified": True},
        {"from": 1, "to": 3, "label": "A1", "verified": False},
        {"from": 4, "to": 6, "label": "A1", "verified": False},
        {"from": 7, "to": 9, "label": "A2", "verified": False},
        {"from": 10, "to": 11, "label": "A2", "verified": False},
        {"from": 12, "to": 13, "label": "A2", "verified": False},
        {"from": 14, "to": 14, "label": "A2", "verified": False},
        {"from": 15, "to": None, "label": "B1", "verified": False}],  # visé: B1
    ("expression", "premiere", "LVA"): [
        {"from": 0, "to": 0, "label": None, "verified": True},
        {"from": 1, "to": 4, "label": "A1", "verified": True},
        {"from": 5, "to": 11, "label": "A1", "verified": False},
        {"from": 12, "to": 14, "label": "A2", "verified": True},
        {"from": 15, "to": 17, "label": "A2", "verified": False},
        {"from": 18, "to": 19, "label": "A2", "verified": False},
        {"from": 20, "to": 29, "label": "B1", "verified": True},
        {"from": 30, "to": None, "label": "B2", "verified": False}],  # visé: B1 / B2
    ("expression", "premiere", "LVB"): [
        {"from": 0, "to": 0, "label": None, "verified": True},
        {"from": 1, "to": 3, "label": "A1", "verified": False},
        {"from": 4, "to": 7, "label": "A1", "verified": True},
        {"from": 8, "to": 9, "label": "A1", "verified": False},
        {"from": 10, "to": 11, "label": "A1", "verified": False},
        {"from": 12, "to": 15, "label": "A2", "verified": True},
        {"from": 16, "to": 19, "label": "A2", "verified": False},
        {"from": 20, "to": None, "label": "B1", "verified": False}],  # visé: A2 / B1
    ("expression", "terminale", "LVA"): [
        {"from": 0, "to": 0, "label": None, "verified": True},
        {"from": 1, "to": 8, "label": "A1", "verified": True},
        {"from": 9, "to": 14, "label": "A2", "verified": True},
        {"from": 15, "to": 21, "label": "B1", "verified": True},
        {"from": 22, "to": 27, "label": "B1+", "verified": True},
        {"from": 28, "to": 34, "label": "B2-", "verified": False},
        {"from": 35, "to": 39, "label": "B2-", "verified": False},
        {"from": 40, "to": None, "label": "B2", "verified": False}],  # visé: B2
    ("expression", "terminale", "LVB"): [
        {"from": 0, "to": 0, "label": None, "verified": True},
        {"from": 1, "to": 5, "label": "A1", "verified": True},
        {"from": 6, "to": 8, "label": "A1", "verified": False},
        {"from": 9, "to": 12, "label": "A2", "verified": True},
        {"from": 13, "to": 15, "label": "A2+", "verified": True},
        {"from": 16, "to": 17, "label": "A2+", "verified": False},
        {"from": 18, "to": 19, "label": "A2+", "verified": False},
        {"from": 20, "to": None, "label": "B1", "verified": False}],  # visé: B1
}


def note_bands(modalite: str, classe: str, track: str):
    """Return the official /20 note->attestation bands for the reference UI."""
    return NOTE_BANDS.get((modalite, classe, track), [])


# Official "visé" (class target) per (modalite, classe, track), from the
# rightmost column of the official conversion tables.
NOTE_VISE = {
    ("comprehension", "premiere", "LVA"): "B1 / B2",
    ("comprehension", "premiere", "LVB"): "A2 / B1",
    ("comprehension", "terminale", "LVA"): "B2",
    ("comprehension", "terminale", "LVB"): "B1",
    ("expression", "premiere", "LVA"): "B1 / B2",
    ("expression", "premiere", "LVB"): "A2 / B1",
    ("expression", "terminale", "LVA"): "B2",
    ("expression", "terminale", "LVB"): "B1",
}


# Official score thresholds quoted in the tables (points on the /120 score,
# not the /20 note): comprehension A1>=3, A2>=9, B1>=15, B2>=30, C1>=60,
# C2>=90; expression A1>=4, A2>=12, B1>=20, B2>=40, C1>=80, C2=120.
NOTE_THRESHOLDS = {
    "comprehension": "A1 à partir de 3 points ; A2 à partir de 9 ; B1 à partir de 15 ; B2 à partir de 30 ; C1 à partir de 60 ; C2 à partir de 90 points",
    "expression": "A1 à partir de 4 points ; A2 à partir de 12 ; B1 à partir de 20 ; B2 à partir de 40 ; C1 à partir de 80 ; C2 = 120 points",
}


def compute_attestation(rubric: dict, mapping: list) -> dict | None:
    """Deterministic attestation from per-criterion levels.

    mapping: list of {criterion, suggested_level} from the model report.
    Returns {score, score_max, attestation, modalite, breakdown[], unmapped[]}
    or None for non-attestation rubrics.
    """
    if not rubric.get("attestation"):
        return None
    crit_names = [c["name"] for c in rubric.get("criteria", [])]
    by_name = {m.get("criterion"): m for m in (mapping or [])}
    breakdown, score, unmapped = [], 0, []
    for name in crit_names:
        raw = (by_name.get(name) or {}).get("suggested_level", "") or ""
        lvl = normalize_cefr(raw)
        pts = LEVEL_POINTS.get(lvl)
        if pts is None:
            unmapped.append(name)
        breakdown.append({"criterion": name, "level": raw, "level_norm": lvl,
                          "points": pts})
        score += pts or 0
    return {
        "score": score,
        "score_max": SCORE_MAX,
        "modalite": rubric.get("modalite", "expression"),
        "attestation": attestation_from_score(score, rubric.get("modalite", "expression")),
        "breakdown": breakdown,
        "unmapped": unmapped,
    }


# ---------------------------------------------------------------- legacy generic presets
_LEGACY = [
    {"id": "bac-written",
     "name": "French Baccalaureate - Written (Projet / Composition)",
     "mode": "written", "is_preset": True,
     "criteria": [
        {"name": "Task Response & Content",
         "description": "Relevance and adequacy to the task; development and depth of content; personal investment and argumentation."},
        {"name": "Coherence & Organization",
         "description": "Logical flow, paragraphing, explicit structuring, connectives and discourse markers guiding the reader."},
        {"name": "Morphosyntactic Control",
         "description": "Range and accuracy of sentence structures: tenses, agreement, word order, complex/compound sentences, advanced structures where present."},
        {"name": "Lexical Resource",
         "description": "Range and precision of vocabulary: B2/C1-level items, collocations, topic-specific vocabulary, spelling."}]},
    {"id": "bac-oral",
     "name": "French Baccalaureate - Oral (Epreuves Orales)",
     "mode": "oral", "is_preset": True,
     "criteria": [
        {"name": "Task Response & Content",
         "description": "Relevance to the task, richness and development of content, argumentation, personal investment."},
        {"name": "Fluency & Pronunciation",
         "description": "Fluency (pace, pauses, hesitations) and phonological accuracy (segmentation, word stress, key phonemes, intonation)."},
        {"name": "Language Control",
         "description": "Grammatical range/accuracy and lexical range/precision in spoken production, including discourse markers."},
        {"name": "Overall Communication",
         "description": "Global effectiveness: clarity, appropriateness, capacity to develop a discourse that communicates the intended meaning."}]},
]

PRESETS = ATTES_RUBRICS + _LEGACY
