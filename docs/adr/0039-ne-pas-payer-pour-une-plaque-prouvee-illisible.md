# ADR 0039 — Ne pas payer d'inférence pour une plaque prouvée illisible

- **Statut** : accepté
- **Date** : 2026-08-25
- **Applique** [ADR 0032](0032-l-ocr-n-etait-pas-le-goulot-le-detecteur-de-plaques-l-est.md),
  qui avait mesuré le gâchis sans le corriger, et prolonge
  [ADR 0010](0010-etranglement-du-detecteur-de-plaques.md) d'une garde d'une autre nature.

## Le constat, et il était déjà chiffré

Rapport présent au dépôt (`backend/out/apres-dense.json`), scène de circulation 1080p,
Quadro P1000, ANPR et OCR actives :

| | valeur |
|---|---|
| **framesPerSecond** | **10,18** |
| `stages.plateDetect` | **62,63 ms — 63,7 %** |
| `stages.ocr` | 0,31 ms — 0,3 % |
| `work.plateCropsPerFrame` | 2,46 |
| **`counts.platesPublished`** | **`[]`** |

492 recadrages payés sur la course, 23 véhicules suivis, **zéro plaque publiable**. Le coût
est linéaire en recadrages — 21,5 ms pour un, 139,7 pour huit — parce que chaque véhicule
paie une inférence 640×640 entière.

Et ce n'est pas un accident de réglage : sur une vue de circulation, les plaques font moins
de 48 px alors que le plancher de lecture est mesuré à 64 (invariant 12). **Aucune plaque
ne *peut* y être publiée.** Le service le disait déjà, véhicule par véhicule, avec
`plate_unread_reason = too_small` et la largeur de la meilleure plaque vue.

## Ce que les gardes existantes ne couvraient pas

- **`min_vehicle_width_px`** (96 px) est un nombre unique, écrit à la main, valable pour
  toute la scène. Sa propre docstring dit « à calibrer au banc » — sans qu'aucun outil ne
  publie le rapport plaque/véhicule dont il dépend ;
- **`max_consecutive_misses`** ne couvre que « détection soumise, **rien trouvé** ». Elle
  est muette sur le cas dominant ici : **trouvé, mais toujours trop petit** ;
- **les deux `stop_when_confident` sont inertes sur cette scène**, et c'est ce qui la rend
  si coûteuse. Ils s'appuient sur `PlateTextVote.is_confident`, qui exige trois lectures à
  ≥ 0,88 : sans plaque lisible, aucun vote ne s'établit, donc « la plus grosse économie du
  dispositif » ne se déclenche jamais.

## La décision

Dès qu'une piste a reçu **une seule** détection réelle, on connaît le rapport
`largeur_plaque / largeur_véhicule` **de cette piste-là** — mesuré sur elle, pas estimé sur
la scène. On sait donc exactement quelle largeur de véhicule il faudrait pour franchir le
plancher de lecture, et on peut se taire tant qu'elle n'est pas atteinte.

`PlateDetectPolicy` retient `best_ratio` et un compteur d'illisibilités **consécutives** ;
`should_detect` refuse une piste dont `largeur_véhicule × best_ratio < plancher`.

### Ce qui distingue cette porte d'un abandon

`largeur_véhicule × rapport ≥ plancher` redevient vrai **tout seul** quand le véhicule
s'approche. Pas de facteur de croissance à régler, pas d'hystérésis, pas de compteur à
faire expirer : c'est une **mesure**, pas un délai. La porte *suspend*, elle n'abandonne
pas.

C'est ce qui répond à l'objection décisive contre un simple compteur d'abandon — « on
perdrait la plaque que cette piste publiera dans trois secondes, à dix mètres d'ici ». Un
test dédié le verrouille : la même piste redevient détectée quand sa boîte atteint 640 px.

### Pourquoi le défaut est armé, et pourquoi ce n'est pas un gain silencieux

La règle du dépôt est qu'un gain de vitesse payé en rappel doit être un réglage explicite,
jamais un défaut. Elle est respectée, et pour une raison structurelle : **le nombre comparé
est le même** que celui dont `PlateOcrPolicy.should_read` se sert déjà pour refuser de
lire. Une plaque écartée par la porte est une plaque que l'OCR aurait refusée — par
construction, pas en moyenne. `platesPublished` ne peut pas bouger.

Ce qui est réellement payé est ailleurs, et il faut le dire : **le rectangle** disparaît
sur ces véhicules, après les `max_anchor_age` images de reprojection. C'était l'objection
d'ADR 0010, et elle reste valable — d'où `TRAFFIC_PLATE_DETECT_READABLE_GATE=false` pour
qui préfère le rectangle à la cadence.

**Sans OCR, la porte ne s'arme jamais.** Le service ne pose le plancher que si un lecteur
tourne réellement : sans lecture, un rectangle sur une plaque de 20 px est exactement ce
que l'utilisateur a demandé, et le couper au nom d'un texte qu'il n'attend pas lui
retirerait sa fonctionnalité.

### Le détail qui pouvait faire échouer tout le mécanisme en silence

**La garde est en position 1 bis, impérativement avant la garde « pas d'ancre ».** Une
piste suspendue ne mesure plus, donc son ancre vieillit et disparaît à `max_anchor_age` ;
la garde 3 rend `True` sans condition dans ce cas, donc placée après, la porte aurait
relancé la piste à *chaque* image et n'aurait **rien** économisé — sans qu'aucun chiffre ne
le signale. Un test la couvre explicitement.

## Deux règles de conception, et pourquoi

- **`best_ratio` est un maximum, jamais la dernière mesure** — même convention que
  `PlateOcrPolicy.record`, et elle penche du bon côté : un maximum rouvre la porte plus
  facilement qu'il ne la ferme. Une piste dont la plaque a été vue large une fois *peut*
  l'être ; laisser une vue de biais écraser ce rapport la fermerait pour de bon ;
- **`readable_min_samples = 2`** : deux mesures basses décrivent une situation, une seule
  décrit un instant — plaque à moitié occultée, mauvais angle. C'est la seule perte de
  plaque possible, et elle est étroite : il faut deux sous-mesures consécutives *et* un
  véhicule qui ne grandit plus ensuite.

## Réglages

| variable | défaut | rôle |
|---|---|---|
| `TRAFFIC_PLATE_DETECT_READABLE_GATE` | `true` | l'interrupteur |
| `TRAFFIC_PLATE_DETECT_READABLE_MIN_SAMPLES` | `2` | mesures basses avant suspension |
| `TRAFFIC_PLATE_DETECT_READABLE_RETRY_EVERY` | `0` | quota d'exploration, désactivé |

Le **seuil**, lui, n'est pas un réglage de la porte : c'est `plate_ocr_min_width_px`, et
c'est tout l'argument. Deux nombres réglables séparément finiraient par diverger, et la
garantie « aucun texte perdu » tomberait avec eux.

## Comment le vérifier

Deux scènes, obligatoirement :

```bash
uv run python scripts/pipeline_bench.py --videos data/jobs/<id> --anpr --ocr \
    --frames 400 --warmup 20 --json out/apres.json --compare out/apres-dense.json
```

Sur la **scène dense** : `work.plateCropsPerFrame` 2,46 → ~0,3-0,6, `stages.plateDetect`
62,6 → ~10-15, `framesPerSecond` **10,2 → ~18-22**. Doivent rester **fixes** :
`trackedVehicles`, `crossings`, `crossedUnique`, `byClass`, `byLine`, `nearMisses`.

Sur la **scène 4K qui publie `A8254S`** : `platesPublished` identique **caractère pour
caractère**. C'est la seule course capable de détecter une perte — sur la scène dense,
elle vaut `[]` avant comme après, donc elle ne prouve rien du risque.

## Ce que cela ne fait pas

- **Cela ne remplace pas un plan mieux cadré.** ADR 0032 le dit et rien ne l'a démenti :
  sur une vue où les plaques font 30 px, les deux gestes qui rendent des plaques sont
  resserrer le champ ou filmer plus défini. La porte rend le temps perdu, elle ne rend pas
  les plaques ;
- **cela ne change rien quand des plaques sont lues.** Une scène où le vote s'établit était
  déjà servie par `stop_when_confident` ; la porte n'y suspend que les pistes lointaines,
  qui ne publiaient rien.
