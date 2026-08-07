# ADR 0010 — L'étranglement du détecteur de plaques, et l'ancre qui le rend invisible

- **Statut** : accepté
- **Date** : 2026-08-07
- **Amende** : [ADR 0007](0007-lecture-du-texte-de-plaque.md), dont l'alternative
  écartée « étrangler le détecteur plutôt que le lecteur » est **renversée**
- **Confirme** : [ADR 0008](0008-precision-de-l-anpr.md) §3 — `plate_mosaic_side`
  reste à `1`, et la mosaïque *adaptative* est refusée

## Contexte

ADR 0007 a mesuré que l'OCR n'est pas le goulot de la chaîne ANPR : la détection
l'est, de deux ordres de grandeur. Elle en a tiré une politique d'étranglement du
**lecteur**, et a explicitement écarté l'étranglement du **détecteur** :

> Corollaire : personne ne doit « optimiser » en étranglant le détecteur. Ses
> boîtes sont dessinées à l'écran ; les produire une frame sur trois ferait
> clignoter des rectangles que l'utilisateur lit comme un défaut de détection. On
> étrangle ce qui ne se voit pas.

Le raisonnement est juste. Sa conclusion l'était aussi — **tant qu'on se
contentait de ne rien produire les images sautées**.

Le coût, lui, est resté. Avec le défaut `mosaic_side = 1`, chaque piste de chaque
image analysée déclenche une inférence 640×640. Mesuré sur une vraie vidéo de ce
dépôt, par `scripts/anpr_bench.py` :

```
  ms/image p50              823.22
  ms/image p95             7151.04
```

Conforme aux ~760 ms d'ADR 0008. Une vidéo de 30 s à 25 fps compte 750 images :
**près de dix minutes de détection de plaques seule**. C'est très probablement
l'expérience rapportée comme « l'analyse ne fonctionne pas ».

Pire, on payait ce goulot pour alimenter un consommateur qui n'écoutait plus : la
politique d'OCR étrangle déjà les *lectures*, mais le détecteur tournait pour
toutes les pistes à toutes les images, y compris celles dont le vote était acquis
et qui ne seraient jamais relues.

## Décision

**Étrangler le détecteur, et supprimer la condition qui l'interdisait** — plutôt
que de contourner cette condition en silence.

### 1. L'ancre de plaque lève l'objection

Une plaque est solidaire de son véhicule dans le plan image. Sur deux ou trois
images consécutives, un véhicule subit une translation et un changement d'échelle
à peu près uniformes, et rien d'autre. On mémorise donc la plaque en coordonnées
**relatives à la boîte du véhicule** (`features/counting/domain/plate_anchor.py`)
et on la reprojette à chaque image sautée.

Le clignotement n'existe plus, donc la condition qui fondait l'interdiction
n'existe plus. C'est cela qui change, et non l'arbitrage débit / justesse.

Une position **absolue** mémorisée ne marcherait pas : c'est le véhicule qui
bouge. Le caractère relatif de l'ancre est ce qui la rend correcte.

### 2. Ce qu'une ancre n'est pas

Une reprojection est une **extrapolation**, pas une mesure. Deux règles en
découlent, toutes deux testées :

- **L'OCR ne lit jamais une boîte reprojetée.** La faire voter fabriquerait de la
  confiance à partir de rien, et deux relectures du même clip pourraient publier
  deux plaques — exactement ce que l'invariant 4 existe pour empêcher.
- **Une reprojection ne nourrit aucun agrégat.** Elle reproduit le score de la
  détection dont elle est issue ; le compter à nouveau ferait de
  `best_plate_score` une mesure de la fréquence des reprojections.

Le contrat porte `stale`, **sérialisé seulement quand il vaut `true`**. C'est une
exception assumée à la règle « `null` explicite » du projet, justifiée comme ADR
0008 justifie de jeter les confiances par caractère : un booléen sur 100 % des
plaques de 45 000 images pèse, et il n'a de sens que dans le cas minoritaire. Le
canvas dessine une ancre d'un trait plus fin — même vocabulaire visuel que les
pistes non confirmées en pointillés.

### 3. Le décalage par identité

`stagger` décale la cadence de chaque identité (`global_id % every_n_frames`).
Sans lui, les pistes d'une image partiraient toutes ensemble une image sur trois :

| | image 0 | 1 | 2 | 3 | 4 | 5 |
|---|---|---|---|---|---|---|
| sans décalage | 0 | 0 | 0 | 6 | 6 | 0 |
| avec décalage | 2 | 2 | 2 | 2 | 2 | 2 |

Le débit moyen est le même et l'expérience bien pire : une image sur trois prend
trois fois plus longtemps que les autres, ce qui se voit dans la cadence affichée.

### 4. La mosaïque adaptative est refusée

Il serait tentant de monter `side` avec le nombre de pistes. Refusé pour deux
raisons cumulées :

1. ADR 0008 §3 **mesure** ce que la mosaïque coûte — −16 % de rappel au côté 2,
   −44 % au côté 3 — et pose qu'on ne troque pas de la justesse contre du débit
   sans que quelqu'un le demande. Une mosaïque *adaptative* fait exactement cela
   **en silence**, et pire : elle rend le rappel fonction du nombre de véhicules
   dans l'image. Deux relectures du même clip donneraient des plaques
   différentes.
2. Elle est redondante avec l'étranglement, qui obtient un facteur comparable
   **sans échanger de rappel** — chaque inférence réellement faite garde sa
   cellule de 616 px.

`plate_mosaic_side` reste donc un réglage de déploiement à `1`. Ce que ce lot
ajoute : un opérateur peut enfin **mesurer** `--mosaic-side 2` sur *sa* scène
avant de décider. C'était l'intention d'ADR 0008, sans les moyens jusqu'ici.

## Mesures relevées

Toutes rejouables par commande — ce que ni 0007 ni 0008 ne permettaient.

### L'échelle de vérité terrain

```bash
cd backend && uv run python scripts/anpr_bench.py --synthetic --truth-ladder \
    --json out/ladder.json
```

| largeur | lectures justes | textes décodés |
|---------|-----------------|----------------|
| 320 px  | **8/8**         | 8              |
| 160 px  | 7/8             | 8              |
| 128 px  | 7/8             | 8              |
|  96 px  | 7/8             | 8              |
|  80 px  | 6/8             | 8              |
|  64 px  | 4/8             | 8              |
|  48 px  | **0/8**         | 8              |

Deux exécutions rendent le **même** tableau : le rendu synthétique est
déterministe pour une graine donnée, et un test le vérifie.

La colonne « décodés » est le chiffre qui explique tout : le réseau rend un texte
à chaque palier, y compris à 48 px où aucun n'est juste. **La chaîne lit du bruit
et le refuse.** Ce n'est pas une panne, c'est le comportement voulu.

### L'étranglement

Trois pistes sur 60 images analysées, dans le vrai pipeline :

| | recadrages soumis | appels |
|---|---|---|
| avant (1/1, sans arrêt sur vote) | 180 | 60 |
| après (défaut, 1/3) | **62** | 60 |

**2,9×**, le bas de la fourchette 3 à 6× attendue. C'est cohérent avec la scène :
aucun vote de plaque ne s'établit sur ces vidéos — les plaques y font 27 à 88 px
pour un plancher à 64 — donc `stop_when_confident` n'économise rien et seule la
cadence joue. Sur une scène où des plaques sont lues, le facteur monte.

## Ce que ce lot ne promet pas

- **Sous ~64 px, rien.** 48 px → 0/8. Les vidéos disponibles (27 à 88 px) sont
  structurellement sous le plancher. Aucun prétraitement ne fabrique de
  l'information absente.
- **La confusion à haute confiance reste.** `GH-901-IJ` lu `GH-901-13` à 0,89 :
  aucun seuil ne l'attrape, et la substitution de glyphes ambigus reste interdite
  (ADR 0007 §5, réaffirmé 0008 §6). Le remède serait une règle de format national
  — point d'extension, pas une promesse.
- **Plafond ~90 % de justesse** sur plaques nettes.

## Conséquences

**Positives.** La partie ANPR d'une analyse va ~3× plus vite sans perdre de
rappel. Le filtre géométrique, extrait dans `counting/domain/plate_geometry.py`,
est désormais traversé par la CI : les 426 gardées / 112 jetées d'ADR 0008 sont
rejouables sur des tuples, sans un pixel. Un banc existe pour la prochaine
optimisation.

**Négatives, et assumées.** Les rectangles de plaque sont exacts une image sur
trois et estimés les deux autres ; `stale` le dit, mais un opérateur qui ne lit
pas le contrat ne le saura pas. `min_width_px` à 64 rend le silence **massif** sur
les vidéos disponibles — d'où les raisons de non-lecture publiées, qui ne sont pas
un confort mais la contrepartie obligatoire de ce lot.

**Point d'extension refusé pour l'instant.** Guider la détection par l'ancre
(chercher la plaque autour de sa position estimée) est prometteur, mais dérive en
silence si l'ancre se décale. À mesurer avant d'adopter.
