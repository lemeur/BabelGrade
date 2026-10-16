"""French student-production content bank for the Annoter test fixtures.

Per subject, three level tiers (low ~A2, mid ~B1, high ~B2). Each subject × tier
carries 4 short variants; the generator rotates variants by student index and
injects the student's first name so each copy is a little different.

Written subjects -> text that becomes the "copy" photo (answers / short essay).
Oral subjects   -> text that is spoken (TTS) and transcribed by Whisper.
"""

# ---------------------------------------------------------------- levels -> tier
def tier_for(level: str) -> str:
    return {"A1": "low", "A2": "low", "B1": "mid", "B2": "high",
            "C1": "high", "C2": "high"}.get(level, "mid")


FIRST_NAMES = ["Léa", "Théo", "Chloé", "Enzo", "Lucas", "Emma", "Nathan", "Manon",
               "Hugo", "Camille", "Jules", "Inès", "Louis", "Alice", "Gabriel",
               "Jade", "Maël", "Zoé", "Arthur", "Lina", "Yanis", "Sarah", "Mehdi",
               "Karim", "Nadia", "Adil", "Rania", "Mickaël", "Fatou", "Ismaël"]


# Written: COMPREHENSION ÉCRITE — questionnaire d'étude de texte (short answers)
COMP_ECRITE = {
    "low": [
        "Le texte parle de l'école. Le titre est important parce qu'il donne le sujet. "
        "L'auteur veut nous donner son avis. Il utilise des mots simples. "
        "Je trouve le texte facile à lire et à comprendre.",
        "Le document est un article. L'auteur raconte une journée à l'école. "
        "Il décrit les cours et les camarades. Le ton est agréable. "
        "Je comprends le sujet principal du texte.",
        "Le titre m'aider à savoir de quoi parle le texte. L'auteur parle de la lecture. "
        "Il donne des exemples. Le texte est court. "
        "Je reconnais quelques mots du vocabulaire.",
        "L'auteur explique pourquoi il aime l'école. Il cite des matières. "
        "Il parle aussi des amis. Le texte est clair. "
        "Je trouve le sujet intéressant pour les élèves.",
    ],
    "mid": [
        "Le texte, « Les réseaux et nous », oppose les avantages et les inconvénients du "
        "numérique à l'école. L'auteur adopte un ton nuancé : il cite les risques "
        "(dépendance, distraction) mais aussi les bénéfices (accès à l'information, "
        "collaboration). Sa thèse finale est que le numérique doit être encadré. "
        "La structure en deux parties, avec un connecteur de contraste « pourtant », "
        "clarifie l'argumentation.",
        "Dans cet extrait, le personnage principal exprime un conflit intérieur. "
        "L'auteur utilise le présent de narration pour donner de l'immédiateté et des "
        "adjectifs expressifs (« immense », « silencieux ») pour créer une ambiance. "
        "Le sous-entendu, suggéré par l'ellipse finale, invite le lecteur à "
        "compléter le sens. L'intention de l'auteur est de susciter l'empathie.",
        "L'article est un texte argumentatif à visée informative. L'auteur s'appuie sur "
        "des chiffres et une citation d'expert pour renforcer sa crédibilité. "
        "La rhétorique de la question, au deuxième paragraphe, implique le lecteur. "
        "Globalement, le registre est plutôt courant, à visée persuasive.",
        "Le récit met en scène un voyage. La chronologie marque le déplacement, "
        "alternant descriptions (paysages) et scènes (rencontres). Les champ lexical "
        "de l'espace et du mouvement structurent le texte. L'auteur propose une "
        "réflexion sur l'ouverture aux autres, portée par la rencontre finale.",
    ],
    "high": [
        "Le texte est un essai argumentatif dont la thèse — que la surveillance "
        "numérique compromet l'autonomie — est défendue par une progression en "
        "entonnoir : de l'observation factuelle à la mise en garde. L'auteur combine "
        "l'argument d'autorité (rapport scientifique) et la concession ("
        "« il ne faut pas diaboliser ») pour anticiper l'objection adverse. La "
        "tonalité oscille entre le didactique et l'impliqué, renforcée par le "
        "champ lexical de l'emprisonnement (« verrou », « cage »). L'intention "
        "est clairement incitative.",
        "L'extrait procède par anaphore (« chaque matin… ») qui rythme le monologue et "
        "construit une escalade de l'angoisse. L'auteur joue sur l'oxymore "
        "(« liberté enchaînée ») et sur une interpellation directe du lecteur pour "
        "l'interroger sur ses propres habitudes. La chute, volontairement ouverte, "
        "déséquilibre le registre lyrique et force la réflexion. La dimension "
        "critique de la société contemporaine domine.",
        "Ce document de presse adopte un angle analytique : l'auteur corrèle trois "
        "phénomènes (urbanisation, télétravail, isolement) et en déduit une "
        "transformation des liens sociaux. Le propos, étayé de données et d'une "
        "anecdote, ménage une nuance de fin (l'espoir d'un « renouveau »). La "
        "structure en entonnoir et l'usage du conditionnel (« pourrait ») "
        "signalent la prudence épistémique de l'auteur.",
        "Le texte de fiction use de l'analepse et de l'anticipation pour replacer "
        "l'action dans sa trajectoire. Le déictique temporel structure le récit et "
        "la focalisation interne restreint le point de vue au personnage. L'auteur "
        "construit l'attente par une hypotexte implicite (la lettre non lue) dont la "
        "révélation différée crée le suspense. La portée morale est sociale.",
    ],
}

# Written: PRODUCTION ÉCRITE — rédaction argumentative
PROD_ECRITE = {
    "low": [
        "Je pense que les réseaux sociaux sont utiles. Avec eux, on parle à ses amis. "
        "On peut aussi regarder des vidéos et apprendre. Mais il faut faire attention, "
        "parce qu'on peut perdre du temps. À mon avis, il faut les utiliser sans "
        "abuser. Voilà mon avis sur les réseaux sociaux.",
        "Le sport est important pour moi. Je joue au football avec mes amis. "
        "Faire du sport est bon pour le corps et pour l'âme. On se met vite dans "
        "un rythme qui nous pousse. Même si c'est parfois fatigant, je continue. "
        "Je recommande à tout le monde de faire du sport régulièrement.",
        "Ma ville est jolie parce qu'elle a un parc et une rivière. On y promène "
        "en famille les dimanches. Les gens sont accueillants et aiment parler. "
        "Les commerces sont pratiques pour les courses. C'est une bonne ville "
        "pour vivre et se reposer tranquillement.",
        "J'aime lire des histoires parce qu'elles me reposent et m'apportent des "
        "évasions. Je lis surtout avant de dormir, dans mon lit, sous la couette. "
        "Les personnages m'amusent souvent. Lire est mon plus grand plaisir "
        "chaque semaine, je ne peux pas m'en passer.",
    ],
    "mid": [
        "À mon avis, il faudrait interdire les réseaux sociaux aux lycéens, au moins "
        "pendant les cours. D'abord, le téléphone est une source de distraction qui "
        "fragilise la concentration, et les études le confirment régulièrement. "
        "Ensuite, la comparaison avec les autres, sur ces plateformes, nourrit un "
        "sentiment d'infériorité qui peut déstabiliser des adolescents en plein "
        "questionnement. Il ne s'agit pas de rejeter le numérique, mais de rappeler "
        "qu'un outil doit rester un moyen, et non une fin en soi.",
        "Le télétravail a-t-il amélioré nos conditions de travail ? En apparence, il "
        "supprime les transports et offre une certaine souplesse horaire. "
        "Pourtant, il brouille les limites entre le professionnel et le personnel : "
        "on répond encore le soir, on s'isole davantage. À terme, c'est la "
        "présence collective, et donc la cohésion, qui en pâtissent. Je pense qu'il "
        "faut plutôt chercher un équilibre, sans tout renverser d'un coup.",
        "Je soutiens qu'il faut redonner à l'école une place plus grande aux arts. "
        "L'expérience musicale ou plastique développe l'imaginaire, renforce "
        "l'expression personnelle et offre une valvule pour ceux qui peinent en "
        "sciences. C'est aussi un facteur d'inclusion : tous y sont à leur niveau. "
        "Enfin, cette ouverture prépare mieux, je crois, les citoyens de demain.",
        "Le développement du tourisme doit rester raisonné. Certes, il rapporte de "
        "l'argent et fait connaître nos régions. Mais, si l'on n'y prend garde, il "
        "détruit les paysages et les modes de vie qu'il met pourtant en scène. "
        "La surfréquentation, en particulier, épuise les lieux et les habitants. "
        "Il faudrait donc réguler, valoriser le tourisme doux et local.",
    ],
    "high": [
        "La surveillance généralisée, en échange d'un sentiment de sécurité, interroge "
        "la notion même de liberté. À première vue, elle semble anodine : une "
        "caméra de plus, un capteur de plus. Or, la somme de ces points de "
        "vigilance dessine, peu à peu, une carte des habitudes de chacun, une "
        "biographie qu'on ne contrôle plus. La question n'est donc pas seulement "
        "technique, elle est philosophique : de quel droit l'autorité compile nos "
        "gestes ? Je défends l'idée que la sécurité ne saurait justifier qu'on "
        "abandonne, silencieusement, notre marge d'autonomie.",
        "Il me semble que la réussite scolaire ne doit plus se résumer à la note. "
        "Longtemps, le système a fonctionné comme une course chronométrée : "
        "mesurer, classer, sanctionner. Or cette logique réduit l'enfant à un "
        "résultat et oublie les compétences qui comptent, savoir apprendre, "
        "coopérer, oser l'erreur. Plutôt qu'un thermomètre, l'école gagnerait à "
        "devenir un jardin : on n'y cherche pas la performance de l'instant mais "
        "la croissance, lente et inégale, de chaque élève.",
        "La ville n'est pas seulement un lieu où l'on habite ; c'est le produit "
        "continu de décisions que l'on confie à quelques-uns. Or, quand la cité se "
        "dessine sans les habitants, elle finit par leur échapper. La place, le "
        "parc, l'angle de rue sont autant de terrains où se joue, concrètement, "
        "l'appartenance. Il me paraît donc essentiel de réintroduire le débat "
        "citoyen au plus près des lieux, sinon nous fabriquons des ensembles "
        "fonctionnels, mais jamais vraiment habités.",
        "Peut-on encore penser le travail sans le concevoir comme une peine ? "
        "L'idée que l'effort se doit d'être amer hérite d'un imaginaire moral qui "
        "associe valeur et souffrance. Or les formes du travail ont changé, et "
        "certains métiers redonnent sens, fierté, même plaisir. Refuser de "
        "s'interroger sur nos représentations, c'est les laisser s'imposer. "
        "Il faut, à mon sens, renouer une discussion franche sur ce que nous "
        "attendons, vraiment, de ce temps où nous passons une part si grande.",
    ],
}

# Oral: COMPREHENSION ORALE — dictée lue à voix haute + réponses brèves
COMP_ORALE = {
    "low": [
        "L'école. Le parc. Le marché. La bibliothèque. La classe. Les amis. "
        "Les livres. Les jouets. La cour. L'horloge. Le tableau. Les cahiers.",
        "Bonjour. Je m'appelle {name}. Je vais à l'école du centre. J'adore l'école. "
        "J'aime la récré. J'aime la lecture. J'ai beaucoup d'amis. "
        "Voilà. Merci de votre écoute.",
        "Le soleil. La pluie. Le vent. La neige. L'été. L'hiver. Le printemps. "
        "L'automne. Les couleurs. Les saisons qui changent dans l'année.",
        "Ma famille. Mon père. Ma mère. Mes frères. Ma sœur. Les grands-parents. "
        "Les voisins. Tout le monde est important pour moi.",
    ],
    "mid": [
        "Le document que je viens d'écouter parle des avantages et des inconvénients "
        "du numérique à l'école. D'abord, il évoque l'accès à l'information, la "
        "collaboration entre les élèves. Puis, il aborde les risques : la "
        "dépendance, la distraction, le manque de concentration. "
        "Enfin, il propose de mieux encadrer l'usage. C'est mon résumé du document.",
        "L'extrait décrit le départ en voyage. Le personnage prépare ses valises, "
        "regarde la ville de loin, puis monte dans le train. L'ambiance est "
        "poétique, mélancolique. On sent un attachement, une nostalgie. "
        "L'auteur suggère que partir, c'est aussi un peu perdre quelque chose. "
        "Voilà ce que j'en retiens de la lecture à voix haute.",
        "L'article analyse les conséquences du télétravail. Les points forts sont la "
        "flexibilité, la suppression des trajets. Les points faibles concernent "
        "l'isolement, la difficulté de déconnecter, la cohésion d'équipe. "
        "L'auteur conclut qu'il faut trouver un juste milieu. "
        "Voici donc mes réponses aux questions de compréhension.",
        "Le récit met en scène une rencontre dans un parc. Deux personnages se "
        "croisent, parlent de leurs souvenirs, partagent un silence. Le texte "
        "insiste sur le mouvement, les paysages. L'auteur évoque l'ouverture aux "
        "autres, l'importance des liens humains. C'est ce que j'ai compris de "
        "l'écoute du document.",
    ],
    "high": [
        "Le texte que je viens de relire défend la thèse selon laquelle la "
        "surveillance numérique compromet l'autonomie individuelle. L'auteur "
        "structure son raisonnement en entonnoir : de l'observation factuelle, il "
        "glisse vers la mise en garde. Il combine l'argument d'autorité, une "
        "concession anticipée, et un vocabulaire marqué par le champ de "
        "l'emprisonnement. L'intention est incitative, presque lyrique. "
        "Voici ce que je retiens de l'analyse.",
        "L'extrait procède par anaphore et construit une escalade de l'angoisse. "
        "L'auteur joue sur l'oxymore « liberté enchaînée » et interpelle le "
        "lecteur pour l'interroger sur ses propres habitudes. La chute, ouverte, "
        "déséquilibre le registre et force la réflexion. La portée critique de la "
        "société contemporaine domine l'ensemble. Je résume ainsi l'écoute du texte.",
        "Le document de presse adopte un angle analytique : il corrèle urbanisation, "
        "télétravail et isolement, et en déduit une transformation des liens "
        "sociaux. Le propos est étayé par des données et une anecdote, et ménage "
        "une nuance de fin. L'usage du conditionnel signale la prudence de "
        "l'auteur. Voici les réponses aux questions de compréhension posées.",
        "Le texte de fiction recourt à l'analepse et à l'anticipation pour replacer "
        "l'action dans sa trajectoire. La focalisation interne restreint le point "
        "de vue au personnage, et l'hypotexte implicite crée le suspense. La "
        "dimension sociale de la morale domine. Telle est, selon moi, la "
        "compréhension que je propose du document écouté.",
    ],
}

# Oral: PRODUCTION ORALE — exposé argumenté (le débit le plus long)
PROD_ORALE = {
    "low": [
        "Bonjour. Aujourd'hui, je vais vous parler de mon sport préféré, le football. "
        "J'adore le football parce que je joue avec mes amis dans le parc. "
        "On court, on s'amuse, on rigole beaucoup. Le sport est important pour "
        "être en forme et avoir la santé. C'est pourquoi je joue tous les "
        "samidis dans la cour du quartier. Voilà, merci.",
        "Bonjour tout le monde. Je vais vous raconter mes vacances. Nous sommes "
        "partis à la mer avec ma famille. J'ai aimé jouer dans l'eau, construire "
        "des châteaux de sable. On a aussi mangé de très bonnes glaces. "
        "C'était vraiment une très belle semaine. Merci de m'avoir écouté.",
        "Je voudrais vous parler de ma ville. Elle est petite mais jolie. Il y a "
        "un parc, une rivière, et beaucoup d'arbres. Les habitants sont très "
        "gentils et accueillants. On s'y promène volontiers le week-end. "
        "C'est une ville où il fait bon vivre et se reposer. Merci.",
        "Aujourd'hui, je vais vous parler de mes livres préférés. J'aime beaucoup "
        "les histoires de contes et de monstres. Je lis surtout avant de dormir, "
        "dans mon lit, sous la couette. Les personnages sont drôles et "
        "amusants. C'est mon plus grand plaisir chaque semaine. Voilà, merci.",
    ],
    "mid": [
        "Bonjour. Je vais vous présenter mon exposé sur les réseaux sociaux chez les "
        "adolescents. Je pense qu'il faudrait les encadrer davantage. D'abord, "
        "l'usage excessif fragilise la concentration et la qualité du sommeil : "
        "on scrolle tard le soir, on répond en pleine nuit. Ensuite, la "
        "comparaison permanente, sur ces plateformes, nourrit un sentiment "
        "d'infériorité qui peut déstabiliser des jeunes. Il ne s'agit pas de "
        "rejeter le numérique, mais de l'utiliser sans en devenir dépendant. "
        "Voilà, merci de votre attention.",
        "Bonjour. Mon sujet aujourd'hui, c'est le télétravail. D'une part, il "
        "supprime les transports et offre une souplesse horaire appréciable. "
        "D'autre part, il brouille les limites entre le travail et la vie "
        "personnelle : on répond encore le soir, on s'isole. À terme, c'est la "
        "cohésion d'équipe qui en souffre. Je crois qu'il faut chercher un "
        "équilibre, sans tout renverser d'un coup. Merci d'avoir écouté.",
        "Bonjour. Je voudrais vous dire pourquoi il faut redonner aux arts une place "
        "plus grande à l'école. L'expérience musicale ou plastique développe "
        "l'imaginaire et renforce l'expression personnelle. Elle offre aussi une "
        "valve pour ceux qui peinent en sciences. C'est enfin un facteur "
        "d'inclusion, car chacun y est à son niveau. Je pense que ça prépare "
        "mieux les citoyens de demain. Voilà, merci.",
        "Bonjour. Je vais vous parler du tourisme et de ce qu'il nous apporte. "
        "Il rapporte de l'argent, il fait connaître nos régions. Mais, si l'on "
        "n'y prend garde, il détruit les paysages qu'il met pourtant en scène. "
        "La surfréquentation épuise les lieux et les habitants. Il faudrait donc "
        "réguler, et valoriser un tourisme plus doux, plus local. C'est mon avis. "
        "Merci de votre écoute.",
    ],
    "high": [
        "Bonjour. Aujourd'hui, je vous propose une réflexion sur la surveillance "
        "numérique. À première vue, elle semble anodine : une caméra de plus, un "
        "capteur de plus. Or, la somme de ces points de vigilance dessine une "
        "carte de nos habitudes, une biographie que nous ne contrôlons plus. "
        "La question n'est donc pas seulement technique, elle est philosophique : "
        "de quel droit l'autorité compile-t-elle nos gestes ? Je défends l'idée "
        "que la sécurité ne saurait justifier qu'on abandonne, silencieusement, "
        "notre marge d'autonomie. Voilà, merci de votre attention.",
        "Bonjour. Je voudrais interroger la notion de réussite scolaire. Longtemps, "
        "le système a fonctionné comme une course chronométrée : mesurer, classer, "
        "sanctionner. Or cette logique réduit l'élève à un résultat et oublie les "
        "compétences qui comptent vraiment : savoir apprendre, coopérer, oser "
        "l'erreur. Plutôt qu'un thermomètre, l'école gagnerait à devenir un "
        "jardin : on n'y cherche pas la performance de l'instant, mais la "
        "croissance, lente et inégale, de chaque élève. Merci d'avoir suivi.",
        "Bonjour. La ville n'est pas seulement un lieu où l'on habite ; c'est le "
        "produit continu de décisions que l'on confie à quelques-uns. Or, quand la "
        "cité se dessine sans les habitants, elle finit par leur échapper. La "
        "place, le parc, l'angle de rue sont autant de terrains où se joue, de "
        "façon très concrète, le sentiment d'appartenance. Il me paraît donc "
        "essentiel de réintroduire le débat citoyen au plus près des lieux. "
        "Sinon, nous fabriquons des ensembles fonctionnels, mais jamais vraiment "
        "habités. Voilà, merci.",
        "Bonjour. Peut-on encore penser le travail sans le concevoir comme une "
        "peine ? L'idée que l'effort se doit d'être amer hérite d'un imaginaire "
        "moral qui associe valeur et souffrance. Or les formes du travail ont "
        "changé, et certains métiers redonnent sens, fierté, même plaisir. Refuser "
        "de s'interroger sur nos représentations, c'est les laisser s'imposer. "
        "Il faut, à mon sens, renouer une discussion franche sur ce que nous "
        "attendons, vraiment, de ce temps où nous passons une si grande part. "
        "Voilà, merci de votre écoute.",
    ],
}


CONTENT = {
    "comp-ecrite": COMP_ECRITE,
    "prod-ecrite": PROD_ECRITE,
    "comp-orale":  COMP_ORALE,
    "prod-orale":  PROD_ORALE,
}


def pick_content(subject_key: str, level: str, student_idx: int,
                 first_name: str | None = None) -> str:
    """Return the text for one student on one subject."""
    tier = tier_for(level)
    variants = CONTENT[subject_key][tier]
    text = variants[student_idx % len(variants)]
    if first_name:
        text = text.replace("{name}", first_name)
    return text
