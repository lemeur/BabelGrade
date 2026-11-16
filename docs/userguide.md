# Guide utilisateur — BabelGrade

> Guide de l'enseignant : évaluer des productions écrites/orales selon le CEFR
> (grilles LVA/LVB /120 et Bac/BTS), avec l'aide optionnelle de l'IA.
> L'interface est disponible en **français, anglais, espagnol et allemand**
> (sélecteur en haut à droite).

---

## 1. Vue d'ensemble

| Onglet | À quoi ça sert |
|---|---|
| **Sujets** | Les consignes/tâches de classe (type d'exercice, niveau cible, documents joints). |
| **Évaluations** | L'historique de vos évaluations + le rapport détaillé. |
| **Grilles** | Les grilles d'évaluation disponibles (Bac, BTS, CEFR attestation LVA/LVB). |
| **Élèves** | La liste des élèves. |
| **Tâches** | La file de traitement : tout ce qui tourne en arrière-plan (transcription Whisper, analyse IA…). |
| **Docs** | Cette documentation (README, guide utilisateur, architecture async). |

Deux façons de travailler :

- **Boucle A — IA d'abord** : lancer l'analyse IA, puis relire/ajuster la matrice critère par critère.
- **Boucle B — Évaluer d'abord** : noter vous-même chaque critère, demander l'avis IA en option, comparer, trancher.

---

## 2. Lancer une analyse (Boucle A)

1. **Analyser** (icône ✏️ en haut) : ouvrez le panneau d'analyse.
2. Choisissez le **type** de production : écrit / oral (audio) / document.
3. Collez le **texte** (ou déposez photos / PDF / audio).
4. Choisissez la **grille** — c'est le choix le plus important : il détermine
   la structure du rapport (attestation LVA/LVB, Bac écrit/oral, BTS…).
5. Définissez le **niveau cible** (ex. B2) et l'élève (facultatif).
6. **Lancer l'analyse IA** → l'app passe en file de traitement (voir §5).
   Pendant ce temps, les tokens du modèle défilent dans la carte « travail en cours ».

À la fin, le rapport s'ouvre dans **Évaluations** : matrice des critères,
attestation (si grille attestation), note /20, feedback de l'élève.

---

## 3. Évaluer d'abord (Boucle B)

1. Cliquez **✍️ Évaluer** : un rapport « squelette » est créé immédiatement
   (matrice vide, attestation 0/120) — aucune attente LLM.
2. Notez chaque critère : cliquez sur le niveau (A1…C1), ajustez les points.
   Le **score /120 et le niveau attesté se recalculent en direct**.
3. En option, lancez l'**avis IA** depuis la bannière en bas du rapport :
   - **IA en aveugle** : l'IA évalue sans voir vos niveaux (avis indépendant).
   - **IA au courant** : l'IA voit vos niveaux et les justifie/critique.
4. La colonne **IA** du tableau attestation montre l'avis critère par critère :
   `B2 ✓` = aligné avec vous, `B2 ≠` = divergence (à trancher).
5. Le résumé de la bannière compte **confirmés** et **divergences**.
   Re-lancer l'IA remplace l'avis précédent (**last opinion wins**) — votre
   matrice d'enseignant est **jamais** écrasée.

---

## 4. Le rapport (Évaluations → détail)

- **En-tête** : titre, élève, tâche, date, statut (squelette ✍️ / complet).
- **Attestation LVA/LVB** (grilles attestation) : niveau par critère (modifiable),
  niveau IA (lecture seule), points, **score /120 + niveau attesté** recalculés en direct.
- **Note /20** : sélection de la classe/seuils + conversion du score /120.
- **Proof Matrix** (grilles non-attestation) : niveau suggéré + justifications de l'IA.
- **Feedback élève** : succès, axes de progression — copiable en un clic.
- **Bannière IA** (état variable) : *picker* (choix blind/aware + Lancer) →
  *en cours* (tokens + ✕ Annuler) → *done* (recap ✓/≠ + ↻ Re-lancer).

Chaque évaluation reste modifiable : changez un niveau, le rapport se recalcule,
puis **enregistrer** pour persister.

---

## 5. Tâches (file de traitement)

Les traitements longs (transcription Whisper, analyse IA, relances IA) ne
bloquent jamais l'interface : ils s'exécutent **en arrière-plan** dans la file.

- **Compteurs en direct** : `⏳ en attente · ▶ en cours · ✓ finis`.
- Chaque ligne : type (Analyse IA / Évaluer d'abord / Relance IA), statut,
  phase (Préparation → Transcription → Analyse IA → Enregistrement), durée.
- **▶ Suivre** : ouvre le suivi en direct (tokens, phases) ; vous pouvez
  naviguer ailleurs, la tâche continue.
- **✕** : annule la tâche (coopératif : pris en compte aux bornes de phase).
- **Tâches simultanées (1–4)** : nombre de workers. Si le serveur redémarre,
  les tâches interrompues sont **remises en file** automatiquement.

> Détails techniques : voir **Docs → Architecture des tâches asynchrones**
> (`docs/async-jobs.md`).

---

## 6. Sujets (assignments)

- Créer un sujet : titre, **type d'exercice** (compréhension / expression ×
  écrit / oral), niveau cible, documents joints (consigne, document source,
  consignes d'évaluation).
- Le **type d'exercice** pilote la grille d'évaluation : quand on choisit le
  sujet dans l'Évaluateur, le canal (écrit/oral) est pré-coché et la grille
  LVA/LVB correspondante est suggérée — *Compréhension* → grille
  « Compréhension (écrit & oral) » ; *Expression* → « Expression écrite » ou
  « Expression orale » selon le canal. Le type apparaît en pastille dans la
  liste des sujets (colonne *Type*, filtre *Mode*).
- Les sujets alimentent le formulaire d'analyse (pré-remplissage) et
  s'affichent dans l'historique.

---

## 7. Grilles

Grilles intégrées (CEFR attestation LVA/LVB, Bac écrit/oral, BTS oral/écrit).
Le choix de grille détermine : nombre de critères, colonne IA, attestation
/120, seuils de note /20. Les grilles sont en lecture seule (pré-configurées
côté serveur).

---

## 8. Élèves & Données

- **Élèves** : liste des élèves (créables depuis l'analyse).
- **Données** : accès brut aux ressources (API) et purge des données.

---

## 9. Astuces & pièges

- **L'IA est un conseil, pas une décision** : la matrice d'enseignant fait foi.
  Un re-lancer d'IA ne modifie jamais vos niveaux.
- **Divergence ≠ erreur** : l'IA a un biais de niveau (souvent plus généreux sur
  la communication). Lisez la justification avant de trancher.
- **Audio long** : la transcription Whisper peut durer ; suivez la tâche dans
  l'onglet Tâches plutôt que de patienter dans le formulaire.
- **Mobile** : le rapport passe en cartes empilées sous 760 px ; tout reste
  accessible (tableaux → cartes).
- **Langue** : le contenu produit par l'IA suit la langue de l'interface
  choisie au lancement.

---

## 10. Dépannage

| Symptôme | Piste |
|---|---|
| « Tâche en erreur » | Voir le message `error` dans l'onglet Tâches ; souvent LLM indisponible ou audio illisible. |
| Rapport « squelette » figé | Le job `evaluate` a échoué avant persistance — relancer l'évaluation. |
| Colonne IA vide après un run-ai terminé | La bannière doit être en état *done* avec recap ; sinon vérifier les Tâches (job annulé/erreur). |
| Lenteur globale | Réduire **Tâches simultanées** à 1 (le modèle LLM local est en monomachine). |

---

*Références : README (architecture), guide UX (recommandations d'ergonomie),
architecture des tâches asynchrones.*
