#!/usr/bin/env python3
"""Generate static/grid-i18n.js — display translations for the official CEFR
grids (LVA/LVB). Keys are the CANONICAL FRENCH strings (from app/rubrics.py);
the LLM prompt + backend matching + counter-proposal all key on those, so the
stored text stays French and only the display is translated.

Run:  /tmp/bg_venv/bin/python scripts/gen_grid_i18n.py
Output: static/grid-i18n.js  (window.BG_GRID_I18N = {en/es/de:{names,grids,descs,gaps}})
"""
import json, sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import rubrics as R

# ---- collect canonical strings (order-stable, deduped) ----
def unique(seq):
    out = []
    for x in seq:
        if x not in out:
            out.append(x)
    return out

NAMES = []
DESCS = []
for grid in (R._COMP_CRITERIA, R._ECRITE_CRITERIA, R._ORAL_CRITERIA):
    for c in grid:
        NAMES.append(c["name"])
        DESCS.append(c["description"])
GAPS = []
for grid in (R._COMP_CRITERIA, R._ECRITE_CRITERIA, R._ORAL_CRITERIA):
    for c in grid:
        for lvl in c.get("gaps", {}).values():
            for v in lvl.values():
                GAPS.append(v)
NAMES = unique(NAMES); DESCS = unique(DESCS); GAPS = unique(GAPS)
GRIDS = [r["name"] for r in R.ATTES_RUBRICS]

# =================================================================
# Translations. Each list is IN THE SAME ORDER as NAMES / DESCS / GAPS / GRIDS
# collected above (verified by the coverage assert below).
# =================================================================

EN = {
"names": [
 "Identification of the context / enunciative situation",
 "Identification of meaning networks",
 "Identification of communication strategies",
 "Content quality",
 "Coherence in discourse construction",
 "Accuracy of the written language",
 "Language richness",
 "Continuous oral expression",
 "Oral interaction",
 "Accuracy of the spoken language",
],
"grids": [
 "LVA/LVB Attestation — Comprehension (written & oral)",
 "LVA/LVB Attestation — Written expression",
 "LVA/LVB Attestation — Oral expression",
],
"descs": [
 "C2: understands, with few exceptions, all elements related to the context and the enunciative situation. C1: identifies fine details or the implicit, placing them in the context. B2: identifies the richness of a context or situation, including by noting implicit elements. B1: notes detailed information about the context (purpose, stakes, narrative perspective, experiences) and links them. A2: notes explicit information about the context (theme, places, people, events). A1: notes isolated, simple pieces of information and partly links them together.",
 "C2: understands, with few exceptions, meaning networks. C1: identifies and analyses the internal logic of a document or file, distinguishing digression where applicable. B2: identifies the overall coherence of a document or file: main reasons for/against, reconstructs a chronology, spots chronological breaks. B1: notes the main meaning-bearing elements: general plan of the text, simple causal links. A2: understands overall: main subject, grouping of terms from the same semantic field. A1: builds an opening to comprehension by noting words or expressions.",
 "C2: understands, with few exceptions, communication strategies. C1: identifies the articulation between documents; the tone of a statement (irony, humour, interpersonal strategies). B2: detects an intention by distinguishing the expression of a point of view from the statement of facts; identifies implicit elements of the inter-documentary articulation. B1: identifies the expression of points of view, wishes and/or perspectives; the nature of the articulation between documents (chronological, illustrative, or contrastive link). A2: identifies the nature of the document(s) and relates it to a few content elements. A1: notes a few evident data or features of a document (dates, titles, paragraphs).",
 "C2: conveys fine nuances of meaning on a complex topic. C1: treats the topic and produces a fluent, convincing text backed by relevant (inter)cultural elements. B2: produces a clear, detailed and overall effective text, including by drawing on certain (inter)cultural elements. B1: intelligible and reasonably developed writing, with reference to a few (inter)cultural elements. A2: treats the topic, even if the production is short. A1: simply begins a written production related to the topic.",
 "C2: produces coherent, structured discourse on a complex topic. C1: complex narrative or argumentation with a mastered use of linguistic means of structuring and articulation. B2: narrative or argumentation showing the relationship between facts and ideas in a well-structured text. B1: reports experiences by describing one's feelings and reactions; presents and illustrates a point of view; tells a story coherently. A2: presents an experience or a point of view using basic connectors. A1: enumerates information about oneself or others.",
 "C2: a very high degree of grammatical accuracy, including complex structures on a complex topic. C1: a high degree of accuracy maintained throughout the writing, including complex structures. B2: good command of simple and common structures; errors on complex structures do not lead to misunderstandings. B1: good command of simple and common structures; errors on simple structures do not hinder reading. A2: text immediately understandable despite frequent errors. A1: text globally understandable but whose reading is not easy.",
 "C2: a very large, relevant lexical repertoire including idiomatic expressions, nuances of wording and varied structures even on a complex topic. C1: a large, relevant repertoire including idiomatic expressions, nuances of wording and varied structures. B2: sufficient range of vocabulary and structures to allow precision and variety of expression. B1: limited lexical range, requiring periphrasis and repetition. A2: words fitted to the communication intent, despite a limited lexical repertoire. A1: text intelligible despite a very limited vocabulary.",
 "C2: conveys fine nuances of meaning on a complex topic. C1: develops a complex argumentation based on (inter)cultural aspects, in a synthetic and fluent way, while ensuring it is well received. B2: develops a relevant, well-supported point of view, including through reformulations that do not break the thread of the discourse; nuances by drawing on (inter)cultural references. B1: presents a point of view simply, illustrated by examples and references to (inter)cultural aspects; structured discourse (causal relationships, comparisons). A2: expresses an opinion in simple terms; short discourse, juxtaposed elements. A1: expresses an opinion in very simple terms; statements punctuated by pauses, hesitations and false starts.",
 "C2: interacts with ease and spontaneity, skillfully contributing to building the exchange, including by drawing on (inter)cultural references on a complex topic. C1: interacts with ease and contributes skillfully, including (inter)cultural references. B2: argues and tries to convince; reacts with relevance and relaunches the discussion, including to steer the exchange onto familiar or (inter)cultural ground. B1: initiates, sustains and closes a simple conversation on familiar topics, with reference to (inter)cultural aspects. A2: responds and reacts simply. A1: intervenes simply, but communication relies on repetition and reformulation.",
 "C2: uses with good command the full range of phonological features of the target language, always intelligible even on a complex topic. C1: fairly good command of the whole phonological range, always intelligible; the rare language errors do not lead to misunderstandings. B2: accent may be influenced by other languages but does not impede intelligibility; language errors do not lead to misunderstanding. B1: expresses oneself intelligibly despite the influence of other languages; good command of simple structures. A2: expresses oneself clearly enough to be understood, but comprehension requires effort from the interlocutors. A1: uses a very limited repertoire of memorised expressions and words in an understandable way.",
 "C2: a large, relevant lexical repertoire including idiomatic expressions, nuances of wording and varied structures even on a complex topic. C1: a large, relevant repertoire including idiomatic expressions, nuances of wording and varied structures. B2: fairly fluent discourse and statements whose range of vocabulary is sufficient to allow precision and variety of expression. B1: limited lexical range, requiring periphrasis and repetition. A2: words fitted to the communication intent, despite a limited lexical repertoire. A1: statements intelligible despite a very limited vocabulary.",
],
"gaps": [
 "explicit info","detail + links","isolated simple info","richness, implicit",
 "detail, links","fine details placed","richness, implicits","easy comprehension",
 "fine details","with some difficulty","topic + semantic fields","plan + causality",
 "opening to comprehension","overall coherence","plan, causality","internal logic",
 "documents identified","views, links","evident features","intention, implicit",
 "points of view","articulation, tone","intention, implicits","treats the topic",
 "develops it","only begins","detailed, effective","short, minimal ref.","fluent, convincing",
 "less detailed","fine nuances","less convincing","without fine nuances",
 "articulates experiences","describe your feelings","only enumerates","well structured",
 "basic connectors","complex structure","less structured","complex topics",
 "simple structure","less complex topics","understandable despite errors",
 "simple structures mastered","memorised structures","no misunderstanding",
 "frequent errors","sustained accuracy","errors tolerated","very high degree",
 "complex errors remain","lower degree","everyday vocabulary","a margin emerges",
 "memorised vocabulary","nuances, formal register","limited, repetitive","rich, idiomatic",
 "correct but limited","extreme mastery","fewer nuances","less spontaneity",
 "opinion in simple terms","illustrated point of view","well-supported, nuanced",
 "simple, illustrated","complex argumentation","less supported","less complex argumentation",
 "reacts simply","simple conversation held","simple reaction","argues, relaunches",
 "simple conversation","ease, skill","less fine argumentation","less ease",
 "understood with effort","intelligible","interlocutor effort","intelligibility only",
 "rare errors","phonological mastery","less mastery","fitted words",
 "lexical range","very limited vocabulary","precision, variety","periphrasis, repetition",
 "large repertoire","less large repertoire",
],
}

ES = {
"names": [
 "Identificación del contexto / situación de enunciación",
 "Identificación de las redes de sentido",
 "Identificación de las estrategias de comunicación",
 "Calidad del contenido",
 "Coherencia en la construcción del discurso",
 "Corrección de la lengua escrita",
 "Riqueza de la lengua",
 "Expresión oral en continuo",
 "Interacción oral",
 "Corrección de la lengua oral",
],
"grids": [
 "Certificación LVA/LVB — Comprensión (escrito y oral)",
 "Certificación LVA/LVB — Expresión escrita",
 "Certificación LVA/LVB — Expresión oral",
],
"descs": [
 "C2: comprende, salvo raras excepciones, todos los elementos relacionados con el contexto y la situación de enunciación. C1: identifica los detalles finos o lo implícito, situándolos en el contexto. B2: identifica la riqueza de un contexto o de una situación, incluso señalando elementos implícitos. B1: señala información detallada sobre el contexto (objeto, en juego, perspectiva narrativa, experiencias) y establece relaciones entre ellas. A2: señala información explícita sobre el contexto (tema, lugares, personas, sucesos). A1: señala información aislada y simple y la articula en parte entre sí.",
 "C2: comprende, salvo raras excepciones, las redes de sentido. C1: identifica y analiza la lógica interna de un documento o expediente, distinguiendo la digresión cuando procede. B2: identifica la coherencia global de un documento o expediente: principales razones a favor/en contra, reconstituye una cronología, detecta rupturas cronológicas. B1: señala lo esencial de los elementos portadores de sentido: plan general del texto, relaciones de causalidad simples. A2: comprende en general: tema principal, agrupación de términos de un mismo campo léxico. A1: construye una amplitud de comprensión señalando palabras o expresiones.",
 "C2: comprende, salvo raras excepciones, las estrategias de comunicación. C1: identifica la articulación entre documentos; el tono de un enunciado (ironía, humor, estrategias interpersonales). B2: detecta una intención distinguiendo la expresión de un punto de vista de la exposición de hechos; identifica elementos implícitos de la articulación inter-documental. B1: identifica la expresión de puntos de vista, deseos y/o perspectivas; la naturaleza de la articulación entre documentos (enlace cronológico, ilustrativo o de oposición). A2: identifica la naturaleza del/de los documentos y la relaciona con algunos elementos del contenido. A1: señala algunos datos o características evidentes de un documento (fechas, títulos, párrafos).",
 "C2: transmite matices finos de sentido sobre un tema complejo. C1: desarrolla el tema y produce un texto fluido y convincente, respaldado por elementos (inter)culturales pertinentes. B2: produce un texto claro, detallado y globalmente eficaz, incluso apoyándose en ciertos elementos (inter)culturales. B1: escrito inteligible y relativamente desarrollado, con referencia a algunos elementos (inter)culturales. A2: desarrolla el tema, aunque la producción sea corta. A1: inicia simplemente una producción escrita relacionada con el tema.",
 "C2: produce un discurso coherente y construido sobre un tema complejo. C1: narración o argumentación compleja con un uso dominado de los medios lingüísticos de estructuración y articulación. B2: narración o argumentación que muestra la relación entre los hechos y las ideas en un texto bien estructurado. B1: cuenta experiencias describiendo sus sentimientos y reacciones; expone e ilustra un punto de vista; relata una historia de manera coherente. A2: expone una experiencia o un punto de vista usando conectores elementales. A1: enumera información sobre sí mismo o los demás.",
 "C2: grado muy alto de corrección gramatical, incluso en estructuras complejas sobre un tema complejo. C1: grado alto de corrección mantenido a lo largo de toda la redacción, incluso en estructuras complejas. B2: buen dominio de las estructuras simples y corrientes; los errores en estructuras complejas no dan lugar a malentendidos. B1: buen dominio de las estructuras simples y corrientes; los errores en estructuras simples no dificultan la lectura. A2: texto inmediatamente comprensible pese a errores frecuentes. A1: texto globalmente comprensible pero cuya lectura no es fácil.",
 "C2: repertorio léxico muy amplio y pertinente, con expresiones idiomáticas, matices de formulación y estructuras variadas incluso sobre un tema complejo. C1: repertorio amplio y pertinente con expresiones idiomáticas, matices de formulación y estructuras variadas. B2: amplitud del léxico y de las estructuras suficiente para permitir precisión y variedad de las formulaciones. B1: amplitud léxica limitada, que exige el uso de perífrasis y repeticiones. A2: palabras adecuadas a la intención comunicativa, a pesar de un repertorio léxico limitado. A1: texto inteligible pese a un léxico muy limitado.",
 "C2: transmite matices finos de sentido sobre un tema complejo. C1: desarrolla una argumentación compleja basada en aspectos (inter)culturales, de manera sintética y fluida, asegurando su buena recepción. B2: desarrolla un punto de vista pertinente y bien respaldado, incluso mediante reformulaciones que no rompen el hilo del discurso; matiza apoyándose en referencias (inter)culturales. B1: expone un punto de vista de forma simple, ilustrado con ejemplos y referencias a aspectos (inter)culturales; discurso estructurado (relaciones de causalidad, comparaciones). A2: expresa una opinión en términos simples; discurso breve, elementos yuxtapuestos. A1: expresa una opinión en términos muy simples; enunciados interrumpidos por pausas, vacilaciones y falsos comienzos.",
 "C2: interacciona con facilidad y espontaneidad, contribuyendo hábilmente a la construcción del intercambio, incluso aprovechando referencias (inter)culturales sobre un tema complejo. C1: interacciona con facilidad y contribuye hábilmente, incluso con referencias (inter)culturales. B2: argumenta y busca convencer; reacciona con pertinencia y relanza la discusión, incluso para llevar el intercambio a un terreno familiar o (inter)cultural. B1: inicia, mantiene y cierra una conversación simple sobre temas familiares, con referencia a aspectos (inter)culturales. A2: responde y reacciona de manera simple. A1: interviene de forma simple, pero la comunicación se apoya en la repetición y la reformulación.",
 "C2: usa con buen dominio todo el conjunto de rasgos fonológicos de la lengua meta, siempre inteligible incluso sobre un tema complejo. C1: dominio bastante bueno de todo el conjunto fonológico, siempre inteligible; los raros errores de lengua no dan lugar a malentendidos. B2: el acento puede recibir la influencia de otras lenguas pero no obstaculiza la inteligibilidad; los errores de lengua no dan lugar a malentendido. B1: se expresa de manera inteligible a pesar de la influencia de otras lenguas; buen dominio de las estructuras simples. A2: se expresa con suficiente claridad para ser comprendido, pero la comprensión exige esfuerzo de los interlocutores. A1: usa un repertorio muy limitado de expresiones y palabras memorizadas de forma comprensible.",
 "C2: repertorio léxico amplio y pertinente, con expresiones idiomáticas, matices de formulación y estructuras variadas incluso sobre un tema complejo. C1: repertorio amplio y pertinente con expresiones idiomáticas, matices de formulación y estructuras variadas. B2: discurso y enunciados bastante fluidos cuya amplitud léxica es suficiente para permitir precisión y variedad de las formulaciones. B1: amplitud léxica limitada, que exige el uso de perífrasis y repeticiones. A2: palabras adecuadas a la intención comunicativa, a pesar de un repertorio léxico limitado. A1: enunciados inteligibles pese a un léxico muy limitado.",
],
"gaps": [
 "info explícita","detalle + enlaces","info aislada simple","riqueza, implícito",
 "detalle, enlaces","detalles finos situados","riqueza, implícitos","comprensión fácil",
 "detalles finos","con alguna dificultad","tema + campos léxicos","plan + causalidad",
 "amplitud de comprensión","coherencia global","plan, causalidad","lógica interna",
 "documentos identificados","puntos de vista, enlaces","características evidentes","intención, implícito",
 "puntos de vista","articulación, tono","intención, implícitos","desarrolla el tema",
 "lo desarrolla","solo lo inicia","detallado, eficaz","corto, ref. mínima","fluido, convincente",
 "menos detallado","matices finos","menos convincente","sin matices finos",
 "articula las experiencias","describe tus sentimientos","solo enumera","bien estructurada",
 "conectores elementales","estructura compleja","menos estructurada","temas complejos",
 "estructura simple","temas menos complejos","comprensible pese a errores",
 "estructuras simples dominadas","estructuras memorizadas","sin malentendido",
 "errores frecuentes","corrección sostenida","errores tolerados","grado muy alto",
 "subsisten errores complejos","grado menor","vocabulario cotidiano","surge un margen",
 "léxico memorizado","matices, registro formal","limitado, repetitivo","rico, idiomático",
 "correcto pero limitado","dominio extremo","menos matices","menos espontaneidad",
 "opinión en términos simples","punto de vista ilustrado","bien respaldado, matizado",
 "simple, ilustrado","argumentación compleja","menos respaldado","argumentación menos compleja",
 "reacciona de manera simple","conversación simple sostenida","reacción simple","argumenta, relanza",
 "conversación simple","facilidad, habilidad","argumentación menos fina","menor facilidad",
 "comprendido con esfuerzo","inteligible","esfuerzo de los interlocutores","solo inteligibilidad",
 "errores raros","dominio fonológico","menor dominio","palabras adecuadas",
 "amplitud léxica","léxico muy limitado","precisión, variedad","perífrasis, repeticiones",
 "repertorio amplio","repertorio menos amplio",
],
}

DE = {
"names": [
 "Ermittlung des Kontexts / der Äußerungssituation",
 "Ermittlung von Sinnnetzwerken",
 "Ermittlung von Kommunikationsstrategien",
 "Inhaltsqualität",
 "Kohärenz im Diskursaufbau",
 "Korrektheit der Schriftsprache",
 "Sprachliche Vielfalt",
 "Mündliche fortlaufende Darstellung",
 "Mündliche Interaktion",
 "Korrektheit der mündlichen Sprache",
],
"grids": [
 "LVA/LVB-Zertifikat — Text- und Hörverständnis (schriftlich & mündlich)",
 "LVA/LVB-Zertifikat — Schriftlicher Ausdruck",
 "LVA/LVB-Zertifikat — Mündlicher Ausdruck",
],
"descs": [
 "C2: versteht, mit wenigen Ausnahmen, alle Elemente, die den Kontext und die Äußerungssituation betreffen. C1: erkennt feine Details oder das Implizite und ordnet sie in den Kontext ein. B2: erkennt die Reichweite eines Kontexts oder einer Situation, auch durch Aufgreifen impliziter Elemente. B1: nennt detaillierte Informationen zum Kontext (Gegenstand, Anliegen, narrative Perspektive, Erfahrungen) und stellt Bezüge zwischen ihnen her. A2: nennt explizite Informationen zum Kontext (Thema, Orte, Personen, Ereignisse). A1: nennt vereinzelt simple Informationen und stellt teilweise Bezüge zwischen ihnen her.",
 "C2: versteht, mit wenigen Ausnahmen, Sinnnetzwerke. C1: erkennt und analysiert die innere Logik eines Dokuments oder Dossiers, wo angemessen auch die Digression. B2: erkennt den Gesamtkohärenz eines Dokuments oder Dossiers: Hauptgründe für/gegen, stellt eine Chronologie wieder her, erkennt chronologische Brüche. B1: nimmt die wesentlichen Sinn tragenden Elemente wahr: Gesamtplan des Textes, einfache Kausalbeziehungen. A2: versteht im Ganzen: Hauptthema, Zusammenfassung von Wörtern eines semantischen Feldes. A1: beginnt ein Verständnis aufzubauen, indem er Wörter oder Ausdrücke feststellt.",
 "C2: versteht, mit wenigen Ausnahmen, Kommunikationsstrategien. C1: erkennt die Verknüpfung von Dokumenten; den Tonalität eines Äußerungs (Ironie, Humor, zwischenmenschliche Strategien). B2: erkennt eine Intention, indem er die Äußerung einer Meinung von der Darstellung von Fakten unterscheidet; erkennt implizite Elemente der Dokument-zu-Dokument-Verknüpfung. B1: erkennt die Äußerung von Meinungen, Wünschen und/oder Perspektiven; die Art der Verknüpfung zwischen Dokumenten (chronologischer, illustrativer oder gegensätzlicher Bezug). A2: erkennt die Art des/der Dokument(e) und stellt sie mit einigen Inhaltselementen in Bezug. A1: nennt einige offensichtliche Daten oder Merkmale eines Dokuments (Datumsangaben, Titel, Absätze).",
 "C2: bringt feine Sinn Nuancen zu einem komplexen Thema. C1: bearbeitet das Thema und erzeugt einen flüssigen, überzeugenden Text, gestützt auf relevante (interkulturelle) Elemente. B2: erzeugt einen klaren, detaillierten und insgesamt wirksamen Text, auch unter Rückgriff auf bestimmte (interkulturelle) Elemente. B1: verständliche und relativ ausgearbeitete schriftliche Äußerung, mit Bezug auf einige (interkulturelle) Elemente. A2: bearbeitet das Thema, auch wenn die Produktion kurz ist. A1: nimmt einfach eine schriftliche Produktion in Bezug auf das Thema auf.",
 "C2: erzeugt einen kohärenten, aufgebauten Diskurs zu einem komplexen Thema. C1: komplexe Erzählung oder Argumentation mit sicherem Gebrauch sprachlicher Mittel der Strukturierung und Verknüpfung. B2: Erzählung oder Argumentation, die das Verhältnis zwischen Fakten und Ideen in einem gut strukturierten Text zeigt. B1: berichtet von Erfahrungen, indem er Gefühle und Reaktionen beschreibt; stellt und illustriert eine Meinung; erzählt eine Geschichte kohärent. A2: stellt eine Erfahrung oder eine Meinung unter elementaren Konnektoren vor. A1: zählt Informationen über sich selbst oder andere auf.",
 "C2: sehr hohes Maß an grammatikalischer Korrektheit, auch komplexe Strukturen zu einem komplexen Thema. C1: hohes Maß an Korrektheit, das über die gesamte Abhaltung erhalten bleibt, auch in komplexen Strukturen. B2: gutes Beherrschen einfacher und gängiger Strukturen; Fehler in komplexen Strukturen führen nicht zu Missverständnissen. B1: gutes Beherrschen einfacher und gängiger Strukturen; Fehler in einfachen Strukturen erschweren nicht das Lesen. A2: Text trotz häufiger Fehler sofort verständlich. A1: Text im Ganzen verständlich, aber das Lesen ist nicht leicht.",
 "C2: sehr großes, treffendes Wortrepertoire, auch idiomatische Ausdrücke, Formulierungs Nuancen und vielfältige Strukturen, selbst zu einem komplexen Thema. C1: großes, treffendes Repertoire mit idiomatischen Ausdrücken, Formulierungs Nuancen und vielfältigen Strukturen. B2: Wortschatz- und Strukturumfang, der Präzision und Vielfalt der Formulierungen ermöglicht. B1: begrenzter Wortschatzumfang, der Umwege und Wiederholungen erfordert. A2: Wörtern, die zur Kommunikationsabsicht passen, trotz eines begrenzten Wortschatzes. A1: Text trotz sehr begrenztem Wortschatz verständlich.",
 "C2: bringt feine Sinn Nuancen zu einem komplexen Thema. C1: entwickelt eine komplexe Argumentation, gestützt auf (interkulturelle) Aspekte, synthetisch und flüssig, unter Sicherstellung ihrer guten Aufnahme. B2: entwickelt eine relevante, gut gestützte Sichtweise, auch durch Umformulierungen, die den Faden des Diskurses nicht brechen; nuanciert unter Bezug auf (interkulturelle) Referenzen. B1: stellt eine Sichtweise einfach dar, illustriert durch Beispiele und Bezüge auf (interkulturelle) Aspekte; strukturierter Diskurs (Kausalbeziehungen, Vergleiche). A2: drückt eine Meinung in einfachen Worten aus; kurzer Diskurs, nebeneinandergestellte Elemente. A1: drückt eine Meinung in sehr einfachen Worten aus; Äußerungen unterbrochen von Pausen, Zögern und Fehlstarts.",
 "C2: interagiert mit Leichtigkeit und Spontanität, trägt geschickt zum Aufbau des Austauschs bei, auch unter Einbezug (interkultureller) Referenzen zu einem komplexen Thema. C1: interagiert mit Leichtigkeit und trägt geschickt bei, auch mit (interkulturellen) Referenzen. B2: argumentiert und sucht zu überzeugen; reagiert angemessen und belebt die Diskussion, auch um den Austausch auf vertrautes oder (interkulturelles) Terrain zu lenken. B1: nimmt, hält und schließt ein einfaches Gespräch über vertraute Themen, mit Bezug auf (interkulturelle) Aspekte. A2: antwortet und reagiert einfach. A1: greift einfach ein, aber die Kommunikation stützt sich auf Wiederholung und Umformulierung.",
 "C2: verwendet mit gutem Beherrschen die ganze Palette der phonologischen Merkmale der Zielsprache, immer verständlich, selbst zu einem komplexen Thema. C1: recht gutes Beherrschen der gesamten phonologischen Palette, immer verständlich; die seltenen Sprachfehler führen nicht zu Missverständnissen. B2: der Akzent kann unter dem Einfluss anderer Sprachen stehen, beeinträchtigt aber nicht die Verständlichkeit; Sprachfehler führen nicht zu Missverständnis. B1: drückt sich verständlich aus, trotz des Einflusses anderer Sprachen; gutes Beherrschen einfacher Strukturen. A2: drückt sich klar genug aus, um verstanden zu werden, aber das Verstehen erfordert Anstrengung der Gesprächspartner. A1: verwendet ein sehr begrenztes Repertoire auswendig gelernter Ausdrücke und Wörter, verständlich.",
 "C2: großes, treffendes Wortrepertoire, auch idiomatische Ausdrücke, Formulierungs Nuancen und vielfältige Strukturen, selbst zu einem komplexen Thema. C1: großes, treffendes Repertoire mit idiomatischen Ausdrücken, Formulierungs Nuancen und vielfältigen Strukturen. B2: ziemlich flüssiger Diskurs und Äußerungen, deren Wortschatzumfang Präzision und Vielfalt der Formulierungen ermöglicht. B1: begrenzter Wortschatzumfang, der Umwege und Wiederholungen erfordert. A2: Wörtern, die zur Kommunikationsabsicht passen, trotz eines begrenzten Wortschatzes. A1: Äußerungen trotz sehr begrenztem Wortschatz verständlich.",
],
"gaps": [
 "explizite Infos","Detail + Bezüge","isolierte simple Infos","Reichweite, implizit",
 "Detail, Bezüge","feine Details eingeordnet","Reichweite, Implizite","leichte Verständigung",
 "feine Details","mit einigen Schwierigkeiten","Thema + Wortfelder","Plan + Kausalität",
 "Anfang des Verständnisses","Gesamtkohärenz","Plan, Kausalität","innere Logik",
 "Dokumente erkannt","Meinungen, Bezüge","offensichtliche Merkmale","Intention, implizit",
 "Meinungen","Verknüpfung, Tonalität","Intention, Implizite","bearbeitet das Thema",
 "arbeitet es aus","beginnt nur","detailliert, wirksam","kurz, min. Bezug","flüssig, überzeugend",
 "weniger detailliert","feine Nuancen","weniger überzeugend","ohne feine Nuancen",
 "verknüpft Erfahrungen","beschreibe deine Gefühle","zählt nur auf","gut strukturiert",
 "elementare Konnektoren","komplexe Struktur","weniger strukturiert","komplexe Themen",
 "einfache Struktur","weniger komplexe Themen","trotz Fehlern verständlich",
 "einfache Strukturen beherrscht","auswendig gelernte Strukturen","kein Missverständnis",
 "häufige Fehler","sichere Korrektheit","Fehler toleriert","sehr hohes Maß",
 "Fehler in komplexen Strukturen bleiben","geringeres Maß","alltäglicher Wortschatz","es entsteht eine Spanne",
 "auswendig gelernter Wortschatz","Nuancen, gehobener Stil","begrenzt, repetitiv","reich, idiomatisch",
 "korrekt, aber begrenzt","extremes Beherrschen","weniger Nuancen","weniger Spontanität",
 "Meinung in einfachen Worten","illustrierte Sichtweise","gut gestützt, nuanciert",
 "einfach, illustriert","komplexe Argumentation","weniger gestützt","weniger komplexe Argumentation",
 "reagiert einfach","einfaches Gespräch geführt","einfache Reaktion","argumentiert, belebt",
 "einfaches Gespräch","Leichtigkeit, Geschick","weniger feine Argumentation","geringere Leichtigkeit",
 "mit Anstrengung verstanden","verständlich","Anstrengung der Gesprächspartner","nur Verständlichkeit",
 "seltene Fehler","phonologisches Beherrschen","geringeres Beherrschen","passende Wörter",
 "Wortschatzumfang","sehr begrenzter Wortschatz","Präzision, Vielfalt","Umwege, Wiederholungen",
 "großes Repertoire","weniger großes Repertoire",
],
}

def build(canonical, translated):
    assert len(canonical) == len(translated), (
        f"count mismatch: {len(canonical)} canonical vs {len(translated)} translations")
    return {k: v for k, v in zip(canonical, translated)}

out = {
    "en": {"names": build(NAMES, EN["names"]), "grids": build(GRIDS, EN["grids"]),
           "descs": build(DESCS, EN["descs"]), "gaps": build(GAPS, EN["gaps"])},
    "es": {"names": build(NAMES, ES["names"]), "grids": build(GRIDS, ES["grids"]),
           "descs": build(DESCS, ES["descs"]), "gaps": build(GAPS, ES["gaps"])},
    "de": {"names": build(NAMES, DE["names"]), "grids": build(GRIDS, DE["grids"]),
           "descs": build(DESCS, DE["descs"]), "gaps": build(GAPS, DE["gaps"])},
}

# ---- emit JS ----
repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
out_dir = os.path.join(repo, "static")
body = "window.BG_GRID_I18N=" + json.dumps(out, ensure_ascii=False, indent=1) + ";\n"
out_path = os.path.join(out_dir, "grid-i18n.js")
with open(out_path, "w", encoding="utf-8") as f:
    f.write(body)
print(f"wrote static/grid-i18n.js  "
      f"({len(NAMES)} names, {len(GRIDS)} grids, {len(DESCS)} descs, {len(GAPS)} gaps per lang, "
      f"{os.path.getsize(out_path)//1024} KB)")
