# ADR 0054 — Le moteur et son aval se recouvrent, et ce que la mesure en dit

- **Statut** : accepté
- **Date** : 2026-09-01
- **Complète** :
  [ADR 0031](0031-le-decodage-payait-la-resolution-sur-le-chemin-critique.md) —
  même remède, un étage plus haut.
- **Corrige une affirmation de** :
  [ADR 0030](0030-le-detecteur-de-plaques-payait-une-inference-par-vehicule.md),
  reprise dans `CLAUDE.md` : « le seul levier structurel restant est de recouvrir
  l'OCR avec le travail GPU ». Le levier existe, il a été construit et mesuré — il
  rend **1,10× au mieux**, pour une raison que cette ADR écrit noir sur blanc afin
  que personne ne le repropose comme s'il valait le double.

## Contexte

ADR 0031 a sorti le **décodage** du chemin critique : il vit dans un fil, rend des
lots d'avance, et la cadence est passée de `décodage + GPU` à `max(décodage, GPU)`.

Un étage plus haut, la même sérialisation subsistait, et personne ne l'avait
regardée. `UltralyticsEngine.iter_video` est un **générateur** : son corps n'avance
que lorsque le consommateur réclame l'image suivante. Or le consommateur est
`AnalysisService.run_video`, qui entre deux `next()` fait tout l'aval — détection de
plaques, OCR, captures, encodage d'apparence, domaine, sérialisation de la timeline.

Autrement dit, le `track()` du modèle pour l'image *N+1* n'était appelé qu'une fois
l'aval terminé sur l'image *N*, et réciproquement. Deux étages qui se relaient, sur
une machine où la sonde NVML relève **50 % d'utilisation GPU en médiane**
(ADR 0050) : il y avait, sur le papier, la moitié d'une carte à récupérer.

## Décision

Un second fil, générique, au-dessus du moteur : `prefetch(source, depth, name)` fait
tourner le flux de suivi dans un fil et laisse `depth` lots d'avance dans une file
bornée. `TRAFFIC_INFERENCE_PREFETCH_BATCHES` le règle, **`1` par défaut**, `0` rend
le chemin séquentiel d'avant à l'identique.

C'est délibérément le **jumeau exact** de `decode_ahead` — mêmes propriétés, mêmes
modes de panne, écrites une fois de plus parce que l'appelant n'est pas le même :

- le fil meurt avec le générateur, et `source` est **fermée explicitement** : elle
  tient le fil de décodage, dont la fermeture en cascade passerait sinon par le
  ramasse-miettes ;
- le producteur ne bloque jamais indéfiniment sur une file pleine ;
- une exception traverse et est relevée dans le fil appelant ;
- **le `join` n'est pas borné**, et c'est le seul écart avec `decode_ahead`. Le fil
  tient le *modèle*, sous le bail d'`iter_video` : rendre la main pendant qu'un
  `track()` est en vol relâcherait le bail sous l'inférence, et deux jobs
  partageraient une instance — invariant 9, c'est-à-dire des chiffres plausibles et
  faux. `yield from` et non une boucle `for`, pour la même raison : c'est lui qui
  ferme le flux quand l'appelant referme le sien (annulation, borne de fenêtre).

**Aucun chiffre ne change**, et c'est ce qui rend le changement livrable : ni l'ordre
des appels au modèle, ni leurs arguments, ni l'état du tracker, ni l'ordre des images
rendues. Seul l'*instant* où le travail a lieu change. Les cinq paires de courses
alternées ci-dessous rendent les **mêmes** véhicules suivis, les mêmes
franchissements, les mêmes quasi-franchissements et les mêmes plaques publiées.

## Mesures

Courses **alternées sur carte chaude** (les deux pièges de `CLAUDE.md` : l'horloge
GPU monte de 885 à 1518 MHz au fil d'une session, et le bruit entre deux courses
identiques est de 11 %). 1080p, `yolov8n`, 250 images mesurées, 30 de rodage.

| fenêtre de la scène | `prefetch=0` | `prefetch=1` | rapport |
|---|---|---|---|
| OCR active, 2 plaques publiées | 23,40 / 23,91 / 22,33 | 26,39 / 24,64 / 25,42 | **1,10×** |
| plaques localisées, jamais lues | 29,55 / 29,08 | 31,02 / 30,72 | 1,05× |
| plaques sous le plancher, OCR muette | 42,33 / 42,10 | 40,37 / 42,36 | 1,00× |

**Le rapport seul ne prouverait rien** — 1,10× est à la limite du bruit de 11 %.
Ce qui rend le résultat crédible est le **signe** : `prefetch=1` gagne les cinq
paires alternées où il y a quelque chose à recouvrir, et perd une des deux paires où
il n'y a rien.

## Pourquoi ce n'est pas le double, et pourquoi il ne faut pas le reproposer

L'hypothèse de départ était : le moteur tient le GPU, l'aval tient le CPU, donc les
recouvrir donne `max` au lieu de la somme. Le profil mesuré la dément.

Partage par image sur la fenêtre où l'OCR travaille :

| poste | ms | où |
|---|---|---|
| `plateDetect` | 22,0 | dont **17,9 de passe avant**, c'est-à-dire du GPU |
| `inference` | 10,2 | GPU |
| `tracker` | 4,0 | CPU |
| `preprocess` | 3,8 | CPU |
| `postprocess` | 3,5 | mixte |
| `ocr` | 6,4 | CPU (onnxruntime, aucun provider CUDA ici) |

L'aval **est lui aussi du travail GPU**, aux deux tiers. Deux flux CUDA sur une même
carte se sérialisent : recouvrir la détection de plaques avec la détection de
véhicules ne rend rien, quel que soit le nombre de fils. Seules les **moitiés CPU**
se cachent l'une derrière l'autre — l'OCR, les recadrages, le domaine —, et c'est
exactement ce que dit la troisième ligne du tableau de mesures : sur une scène où
l'OCR ne se déclenche jamais, le gain est nul, au chiffre près.

Deux corollaires à retenir avant d'ouvrir un nouveau lot de performance ici :

- **la phrase « l'OCR est sérialisée avec le GPU, la recouvrir est le levier
  restant » est réglée**, et elle valait 10 %. Ne pas la relire comme une réserve
  encore disponible ;
- **le vrai poste reste la détection de plaques**, et ADR 0032 a déjà mesuré ses
  deux seules issues : moins de recadrages (ce que font ADR 0039 et l'étranglement
  d'ADR 0010) ou un côté d'entrée plus petit (rappel effondré, 94 → 22 → 0 plaques
  pour 640 → 448 → 320). Le lot ne l'amortit presque pas — ADR 0032 mesure 21,5 ms
  pour un recadrage et 139,7 pour huit, soit 17,5 ms de calcul par recadrage : c'est
  du calcul, pas du coût d'appel.

## Conséquences

- `TRAFFIC_INFERENCE_PREFETCH_BATCHES` (défaut `1`, `0` désactive). `1` suffit : ce
  qui recouvre est le lot d'avance, pas la profondeur de la file. Au-delà, on retient
  des images décodées **et** leurs résultats de suivi en mémoire sans rien gagner.
- Empreinte mémoire : un lot d'images décodées et ses résultats de suivi en plus de
  ce que `DECODE_BUDGET_BYTES` autorisait déjà.
- Une annulation coûte au plus un lot d'inférence de plus, le temps que le fil
  observe l'arrêt — le `join` n'étant pas borné, elle ne peut pas rendre la main
  avant.
- `scripts/pipeline_bench.py --prefetch N` permet de rejouer les courses alternées
  ci-dessus sans toucher à l'environnement. **Le rapport du banc devient trompeur si
  on l'additionne** : les postes sont désormais concurrents, donc leur somme dépasse
  le temps par image, et `decodeAndOther` (calculé par différence) tombe à zéro.
- Le direct n'est pas concerné : les images y arrivent une par une, et il n'y a rien
  à précalculer.

## Alternatives écartées

- **Un fil par étage (moteur, plaques, OCR, captures).** L'aval mute la session de
  comptage que le moteur alimente, et le snapshot de la timeline doit être pris
  **après** les passes ANPR et OCR de la même image (invariant 8). Découper plus fin
  demande de désordonner cela, pour un gain borné par le GPU — qui est déjà le mur.
- **Un second flux CUDA pour le détecteur de plaques.** Le mur est le calcul, pas la
  sérialisation : la carte est à 50 % d'utilisation, mais ce qui reste est du temps
  CPU, pas de la place pour un second noyau.
- **`join` borné, comme dans `decode_ahead`.** Une expiration relâcherait le bail
  sous une inférence en vol. Voir invariant 9.
