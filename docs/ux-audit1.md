# Revue d'ergonomie — BabelGrade

> **Date :** 03/10/2026
> **Périmètre :** application CEFR d'évaluation (grille LVA/LVB « Proof Matrix »)
> **Méthode :** captures réelles des 6 écrans (Analyser, Historique + rapport, Mode Évaluation, Tâches, Élèves, Grilles) en desktop (1280 px) et mobile (390 / 844 px), avec de vraies données (34 productions, 8 tâches, rapport complet avec avis IA). Reconstitution du parcours d'un enseignant en session de correction (30–40 copies). Lecture du code (`static/index.html`, `app/`) pour chiffrer la complexité de chaque proposition.
> **Statut :** proposition uniquement — aucune implémentation. Les choix d'implémentation se feront ensemble par la suite.

## Objectif de l'enseignant

Deux boucles principales :

- **Boucle A — IA d'abord :** choisir tâche → élève → copie (photos / texte / audio) → grille → lancer (60–130 s d'attente) → relire la matrice, ajuster les niveaux → note /20 → sauvegarder → copier le feedback.
- **Boucle B — évaluer d'abord :** même setup → noter critère par critère en Mode Évaluation → IA en option → sauvegarder.

L'interface est déjà solide (le Mode Évaluation est très réussi : 3 colonnes, points, avis IA, total en direct). Les frictions se concentrent sur :

1. le long formulaire d'Analyse,
2. la liste Historique + son détail,
3. l'organisation du rapport.

---

## 🥇 Priorité HAUTE — au quotidien, à chaque copie

### 1. Alléger l'écran Analyser (le plus chargé de l'app)

- **Constat :** 4 cartes numérotées + 2 cartes d'entrée + barre d'action ; la carte 1 seule = 2 textareas + 5 dropzones + 5 lignes « Aucun … joint ». Sur mobile c'est ~5 écrans de scroll sans bouton d'action visible en bas (pas de barre sticky). Les 5 dropzones sont quasi identiques visuellement → bruit.
- **Proposition :** divulgation progressive — afficher par défaut seulement les entrées principales (texte + 1 zone photos pour la copie ; consigne + doc si ad-hoc) ; les alternatives (PDF, audio, photos de consigne) se déplient via un petit « + autre format ». Les lignes de statut « Aucun … » disparaissent quand c'est vide. Le choix de la **grille** (qui détermine tout le rapport) est aujourd'hui en bas de la carte 4 : le rendre plus visible (ou le pré-définir par tâche).
- **Complexité :** moyenne (réorganisation purement UI de `static/index.html`, sans backend ; à vérifier sur desktop + 390 px). ~3–4 h.

### 2. Un seul vrai bouton d'action (dé-doublonner les CTA)

- **Constat :** « Lancer l'analyse IA » (carte du haut) ne fait que *scroller* vers « Analyser la production » (en bas) ; « Évaluer d'abord » existe 2×. Trois manières de faire la même chose, 3 libellés différents → l'enseignant ne sait pas quel bouton « est le vrai ».
- **Proposition :** les deux cartes d'entrée deviennent de simples libellés (ou disparaissent) ; une seule barre d'action en bas : `Analyser avec l'IA` / `Évaluer d'abord` (+ « Enregistrer en tâche » discret).
- **Complexité :** faible (supprimer 2 boutons, déplacer les handlers). ~30 min.

### 3. Historique : le détail doit devenir la vue principale

- **Constat :** le rapport s'ouvre *en dessous* de la liste de 34 lignes ; sur mobile le détail est à ~9 000 px de scroll. Après 30 copies, l'enseignant ré-ouvre l'historique sans cesse : la liste sature l'écran (8 colonnes dont peu de signal, titres « written submission » identiques, élèves « — »).
- **Proposition :** **detail view dédiée** — au clic, le rapport prend la page (liste réduite à une bande filtre en haut avec bouton retour ; sur mobile elle disparaît). Compacter la liste : Élève · Tâche · Niveau · Date · Statut (les colonnes Quand/Type/Grille secondaires disparaissent du scan principal).
- **Complexité :** moyenne-forte (changement de structure de la vue Historique, conservation de la délégation document-level qui est le socle de robustesse de l'app). ~4–6 h.

### 4. Réorganiser le rapport : le « à faire » en premier, pas l'« à lire »

- **Constat :** au-dessus de la table des critères il y a : synthèse exécutive (souvent vide + « confiance: n/a »), le banner IA (un choix IA aveugle / avec niveaux à chaque ouverture), et la carte /20 (selects classe/LVA + 8 chips + seuils répétés 2×) qui repousse la table encore plus bas. L'état « pas encore noté » est dit 4–5 fois (score 0/120, niveau « — », avertissement ambre, matrix tous « ? »).
- **Proposition :** **en-tête du rapport = l'essentiel** : titre + élève + classe + date (déjà là, mais le rendre sticky), **niveau attesté + score /120 + note /20 en un bloc visuel unique** ; la table des critères juste en dessous (c'est l'action principale) ; le banner IA *après* la table (c'est une action optionnelle) ; le bloc /20 compact (seuils affichés 1×) et repliable ; masquer l'avertissement ambre une fois les critères remplis.
- **Complexité :** moyenne (re-template de `renderReport` + repaint des handlers existants `attPaintReport` ; 4 langues). ~4 h.

### 5. Fusionner le « Proof Matrix » dans la table d'attestation

- **Constat :** 2 tables de 4 critères pour la même chose : la table d'attestation (NIVEAU / IA / POINTS) et le Proof Matrix (SUGGÉRÉ + justifications). Quand l'IA a tourné, le niveau « SUGGÉRÉ » duplique la colonne IA. La seule valeur ajoutée du matrix = justifications + preuves citées.
- **Proposition :** pour les grilles d'attestation, **intégrer justification + preuves en ligne dépliable sous chaque critère** dans la table d'attestation (cliquer la ligne) ; le matrix séparé ne reste que pour les grilles non-attestation (Bac).
- **Complexité :** moyenne (les données sont déjà dans `matrix_json` ; c'est du rendu + un peu de CSS). ~3 h.

---

## 🥈 Priorité MOYENNE — confort net, pas bloquant

### 6. Mode Évaluation : rendre la décision frontière plus lisible (le B1/B2 est LE moment de doute)

- **Constat :** les colonnes latérales (A2/B2) ne ressemblent pas à des boutons cliquables (seule la colonne centrale a un cadre) ; les descripteurs B1/B2 sont quasi identiques sans mise en évidence de la différence ; les chips « − erreurs fréquentes » / « + pas de malentendu » ne disent pas par rapport à quoi ; l'encart « L'IA a recommandé B2 » est posé sur la colonne B1 ; on ne voit pas l'effet sur le total (35→40).
- **Proposition :** bouton visible « Choisir A2 » sur les colonnes latérales ; **diff des descripteurs** (surligner le segment qui change) ; libellé des gap-chips « vs B1 : … » ; déplacer l'avis IA sur la colonne qu'elle concerne + lien « voir la preuve » qui ouvre la bottom-sheet `#eval-ai` déjà prévue ; delta du total au survol/au clic (« 35 → 40 »).
- **Complexité :** faible-moyenne (overlay `#eval` autonome, pas de backend). ~2–3 h.

### 7. Couleur de niveau : distinguer B1 de B2

- **Constat :** `levelClass()` regroupe B1 et B2 dans la même teinte bleue (et C1/C2 dans le même violet) → dans l'historique, B1 et B2 se distinguent seulement par la lettre.
- **Proposition :** 4–6 teintes CEFR lisibles (A2 vert clair, B1 bleu clair, B2 bleu foncé, C1 violet clair…).
- **Complexité :** faible (CSS + 4 lignes JS). ~30 min.

### 8. Titres de production par défaut intelligents

- **Constat :** « written submission » × 22 en haut de l'historique (champs optionnels vides) → lignes inutiles.
- **Proposition :** si pas de titre, afficher `Élève · Tâche · date` (fallback côté UI) et générer un titre par défaut côté backend à la création.
- **Complexité :** faible. ~1 h.

### 9. Pendant l'analyse : ne pas bloquer l'enseignant

- **Constat :** 60–130 s d'attente avec un flux de tokens dans une boîte sombre et le formulaire verrouillé.
- **Proposition :** chronomètre + « ~2 min restantes », **naviguer vers l'historique pendant que l'analyse continue en arrière-plan** (SSE découplé de la vue), notification toast à la fin.
- **Complexité :** moyenne (le plus gros morceau technique de la revue — l'état SSE est aujourd'hui lié à la vue Analyse). ~4–5 h.

### 10. Fiche attestation imprimable (print/PDF dédié)

- **Constat :** l'impression actuelle rend tout le rapport (y compris les sections vides). L'attestation est un document administratif : l'enseignant a besoin d'une fiche propre (élève, classe, tâche, niveaux par critère, score /120, niveau attesté, note /20, signature).
- **Complexité :** moyenne (conteneur print dédié + `@media print` existant). ~2–3 h.

---

## 🥉 Priorité Basse — le « joli » / finition

- **11. Masquer les sections vides** (« None recorded. », « confiance: n/a », synthèse vide) → elles ressemblent à un bug. *Fenêtre : faible (~1 h).*
- **12. Statuts de fichiers :** une seule pastille « 3 photos ✓ » au lieu de 5 lignes grises « Aucun … ». *Faible (~1 h).*
- **13. Le ✕ rouge sur chaque ligne** de l'historique donne un effet « mur d'erreurs » ; le `title="Delete"` est en anglais (pas i18n). Passer en gris discret → rouge au survol. *Faible (~30 min).*
- **14. i18n résiduels EN** : « None recorded. », « written submission », « No target », placeholder « Full name » — recette i18n déjà en place dans le skill. *Faible (~1 h).*
- **15. Tâches : ne pas bloquer les fichiers en mode édition** (aujourd'hui : pour changer le document d'une tâche, il faut supprimer + recréer). Bouton « Dupliquer » ou PUT avec fichiers. *Moyenne (~3 h, backend + UI).*
- **16. Mobile :** 5ᵉ onglet rogné (Élèves) dans la nav — raccourcir les libellés ou barre compacte ; **barre d'action sticky** dans l'analyse mobile. *Faible-moyenne (~2 h).*

---

## ⚠️ Ce qui n'a PAS été retenu (vérifié, ce n'est pas un bug)

- La « bande orange avec un × » qui flotte sur les formulaires dans les captures **pleine page** : c'est un **artefact de capture** (le bottom-sheet IA `#eval-ai`, position:fixed fermé, est redessiné à chaque tranche du screenshot). Vérifié dans le DOM : aucun élément visible de ce type. Rien à faire.

---

## 📊 Récapitulatif (importance enseignant / complexité)

| # | Proposition | Importance | Complexité | Effort estimé |
|---|-------------|-----------|-----------|---------------|
| 2 | Dé-doublonner les CTA | Haute | Faible | ~30 min |
| 7 | Couleurs B1/B2 | Haute | Faible | ~30 min |
| 8 | Titres par défaut intelligents | Moyenne | Faible | ~1 h |
| 11–14 | Finitions (sections vides, statuts, ✕, i18n) | Basse | Faible | ~4 h |
| 1 | Alléger l'écran Analyser | Haute | Moyenne | ~3–4 h |
| 4 | Réorganiser le rapport | Haute | Moyenne | ~4 h |
| 5 | Fusionner le Proof Matrix | Haute | Moyenne | ~3 h |
| 6 | Mode Évaluation plus lisible | Moyenne | Faible-moyenne | ~2–3 h |
| 3 | Historique en vue dédiée | Moyenne | Moyenne-forte | ~4–6 h |
| 9 | Non-bloquant pendant l'analyse | Moyenne | Moyenne | ~4–5 h |
| 10 | Fiche attestation imprimable | Moyenne | Moyenne | ~2–3 h |
| 15 | Tâches : éditer les fichiers | Basse | Moyenne | ~3 h |
| 16 | Mobile (nav + barre sticky) | Basse | Faible-moyenne | ~2 h |

**Total estimé :** ~10 items « haut + moyen » ≈ 30 h de travail ; les fins ≈ 8 h.

---

## Note méthodologique

Les captures et scripts de re-capture (desktop/mobile) sont conservés dans `/tmp/elt_review/` (shots + scripts Playwright). Un piège de capture documenté : les captures *pleine page* dupliquent les éléments `position:fixed` (d'où la « bande orange » fantôme) ; pour auditer une page longue, préférer des captures par viewport (`window.scrollTo` + screenshot de la fenêtre).
