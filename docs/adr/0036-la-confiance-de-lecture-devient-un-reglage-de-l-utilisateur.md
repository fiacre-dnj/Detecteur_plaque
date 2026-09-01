# ADR 0036 — La confiance de lecture devient un réglage de l'utilisateur

- **Statut** : accepté
- **Date** : 2026-08-24
- **Amende** [ADR 0007](0007-lecture-du-texte-de-plaque.md), qui avait rangé *tous* les
  seuils d'OCR du côté du déploiement.

## Contexte

L'écran de détection porte deux curseurs — « Confiance véhicules » et « Confiance
plaques » — et il en manquait un troisième que la chaîne appliquait déjà en silence.

`plate_ocr_min_text_score` (0,50) refuse toute lecture moins sûre : la chaîne n'atteint
pas le vote, donc le véhicule reste sans plaque. C'est le bon comportement — une chaîne
affichée est crue — mais c'était un réglage de **fichier**, hors de portée de qui regarde
sa vidéo.

`AnalysisJobConfig` le disait en toutes lettres : « Aucun seuil OCR ici, délibérément : ils
vivent tous dans `Settings`. Ce sont des arbitrages de déploiement […] dont l'utilisateur
ne pourrait pas juger l'effet sur sa vidéo. »

**C'est vrai de tous sauf de celui-là.** Le nombre de cœurs, la cadence d'étranglement,
les variantes de prétraitement sont des questions de machine. « Des plaques fausses, ou pas
de plaques » est une question de scène et d'usage : un contrôle d'accès veut la certitude,
un relevé de fréquentation préfère une plaque douteuse à rien. Personne d'autre que
l'utilisateur devant sa vidéo ne peut trancher.

## La décision

`plateTextConfidence` voyage dans `AnalysisRequest`, **exactement** comme
`plate_confidence` : par requête, et jusqu'à l'adaptateur en argument de `PlateReader.read`.

- `null` — le défaut — garde le plancher du déploiement. C'est ce qui rend le changement
  strictement additif : qui ne touche à rien retrouve ses chiffres ;
- `0` accepte toutes les lectures. **`0` n'est pas `null`**, et les confondre publierait
  des plaques que le serveur refusait jusque-là ;
- la borne haute est `0,95`, pas `1,0` : à `1,0`, plus aucune lecture ne passerait jamais,
  et un curseur qui a une position « ne rien faire du tout » invite à s'y poser.

Le filtre est appliqué **dans l'adaptateur** et nulle part ailleurs : une lecture sous le
plancher ne devient pas un `PlateText`, donc elle ne traverse pas le port, donc elle ne
vote pas. Filtrer aussi côté service laisserait deux endroits décider de ce qui vote, et
ils finiraient par ne plus dire la même chose.

## Ce qui est mesuré

Vidéo réelle, fenêtre de 8 s, ANPR et OCR actives, le vrai `OnnxPlateReader` espionné :

| Demandé | Reçu par le lecteur | Lectures rendues | Plaque publiée |
|---|---|---|---|
| `null` | `None` | 3 | `A8254S` |
| `0.0` | `0.0` | 3 | `A8254S` |
| `0.99` | `0.99` | 0 | *(aucune)* |

Les trois valeurs arrivent **verbatim** jusqu'à l'adaptateur : c'est le point qui manquait,
et c'est l'état où `plate_confidence` est resté jusqu'à ADR 0007 — annoncé au contrat,
sans effet, donc pire qu'absent.

## Ce que ce réglage ne fait pas, et pourquoi c'est écrit à l'écran

**Il ne fait économiser aucune inférence.** La lecture a lieu, puis elle est refusée : le
seul étranglement est celui de `PlateOcrPolicy`, en amont. Monter ce curseur pour accélérer
une analyse est le contresens que la phrase d'aide existe pour éviter — d'où « Décide ce
qui est cru, pas ce qui est lu […] Ne fait gagner aucun temps de calcul ».

**Il ne se confond pas avec « Confiance plaques ».** Celui-là porte sur la
**localisation**, celui-ci sur la **lecture** : une plaque peut être parfaitement encadrée
et illisible, ou l'inverse. Le registre affiche déjà les deux confiances côte à côte pour
cette raison (`bestPlateScore` et la confiance de lecture).

## Conséquences

- **un véhicule dont toutes les lectures sont refusées tombe sur `no_consensus`** — « des
  lectures ont été tentées, aucune ne fait majorité » — et non sur `not_attempted`. C'est
  exact : la tentative a bien eu lieu, et c'est le geste que la raison doit suggérer
  (baisser le curseur, ou resserrer le plan) ;
- **le réglage est subordonné à l'OCR**, elle-même subordonnée à l'ANPR. Sans lecture, il
  n'y a rien à filtrer, et `toRequest` envoie `null` — même règle que `readPlateText` ;
- **`PlateReader.read` prend un troisième paramètre**, optionnel. Toute autre
  implémentation du port — doublure de test comprise — doit l'accepter, et la doublure du
  dépôt l'**applique** au lieu de l'ignorer : un port qui accepte un réglage sans effet est
  exactement ce que cette ADR corrige.
