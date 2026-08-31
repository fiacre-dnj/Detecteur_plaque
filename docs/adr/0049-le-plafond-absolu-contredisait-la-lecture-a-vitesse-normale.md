# ADR 0049 — Le plafond absolu contredisait la lecture à vitesse normale

- **Statut** : accepté
- **Date** : 2026-08-29
- **Abroge** : [ADR 0022](0022-le-plafond-absolu-vaut-30-img-s-par-defaut.md) — son
  défaut, pas son mécanisme.
- **Rétablit le défaut d'** : [ADR 0020](0020-un-plafond-absolu-de-cadence.md).
- **Protège** : [ADR 0019](0019-la-lecture-locale-reste-a-vitesse-normale.md), dont la
  garantie était annulée par le défaut d'ADR 0022 sur toute source au-dessus de
  30 images par seconde.

## Contexte

`analysisSpeed: 1` existe pour une seule raison, écrite en toutes lettres par
ADR 0019 : la vidéo locale se cale sur l'image analysée, donc l'analyse doit avancer
d'une seconde de scène par seconde réelle pour que la lecture paraisse normale.

ADR 0022 a ensuite posé `maxAnalysisFps: 30` par défaut, en jugeant que « 30 img/s est
la cadence vidéo la plus courante, et la poser par défaut ne change rien pour qui filme
à cette cadence ou en dessous ». La proposition est exacte — et sa contraposée n'a pas
été tirée. `ScenePacer.for_video` retient la période la **plus longue** des deux
bridages (`pacing.py:130-137`) :

```
analysisSpeed = 1   sur une source 60 fps  →  1/60 = 16,7 ms  →  60 img/s
maxAnalysisFps = 30                        →  1/30 = 33,3 ms  →  30 img/s
retenu : max(16,7 ; 33,3) = 33,3 ms        →  30 img/s
```

**C'est le plafond qui gagne, et l'aperçu défile à 0,5× le temps réel.** Le réglage
censé garantir la vitesse normale est battu par un défaut posé quatre ADR plus tard,
sans qu'aucun écran ne le dise : l'utilisateur voit une lecture au ralenti et conclut
que la machine est lente.

ADR 0022 énonçait d'ailleurs le fait dans sa troisième conséquence — « une source plus
rapide est désormais bridée par défaut à 30 img/s » — sans voir que ce bridage-là
annule ADR 0019 au lieu de s'y ajouter.

## Mesure

Machine de développement (Quadro P1000), source `1920×1080, 60 fps`, `yolov8n`, comptage
seul, fenêtre de 600 images à partir de 11 s, **GPU déjà chaud** (voir « Ce que la
mesure a aussi montré ») :

| | cadence |
|---|---|
| ce que la machine tient, non bridée | **58,84 puis 58,70 img/s** (courses alternées, écart 0,2 %) |
| cible pour une lecture à vitesse normale | 60 img/s |
| ce que le défaut d'ADR 0022 autorisait | **30 img/s** |

La machine était donc à 98 % de la cible, et le défaut la coupait de moitié.

## Décision

`DEFAULT_SETTINGS.maxAnalysisFps` repasse de `30` à `null`, c'est-à-dire au défaut
qu'ADR 0020 lui avait donné. `analysisSpeed` reste à `1` : **le partage de la machine
n'est pas relâché**, c'est la cadence de scène — le bridage pertinent, parce qu'il est
celui qui décrit ce que l'utilisateur veut voir — qui redevient le seul juge par défaut.
« 30 img/s » et « 60 img/s » restent des choix explicites dans le panneau, pour brider
une machine partagée.

Deux compléments, sans lesquels la décision n'atteindrait personne :

- **une migration de schéma ciblée** (`SETTINGS_SCHEMA_VERSION` 1 → 2). `mergeSettings`
  ne réécrit jamais un choix déjà persisté, et `isSupportedFpsCap(30)` est vrai : un
  poste qui a déjà lancé une analyse garde son `30` en `localStorage` et ne verrait
  **rien** du correctif. `migrateV1` retire le champ — et seulement s'il vaut
  exactement `30`, la valeur que personne n'a choisie. Un `60` ou un `null` en base est
  un choix explicite, et le défaire serait pire que le bug. Le champ est **retiré**
  plutôt que réécrit à `null`, pour qu'un poste migré suive le défaut le jour où il
  rebougera ;
- **un avertissement dans « Configuration système »** quand les deux bridages
  coexistent : « au-dessus de N images par seconde, la source est analysée plus
  lentement que le temps réel et l'aperçu défile au ralenti ». La phrase est
  conditionnelle parce qu'elle doit l'être : la cadence de la source n'est lisible que
  sur la balise `<video>` et ne vit dans aucun état réactif — même limite que celle qui
  prive `describeRange` de la durée.

## Conséquences

- **Aucun compteur ne change.** Le bridage n'ajoute qu'une attente entre deux images ;
  le retirer ne modifie ni une boîte, ni un franchissement, ni un horodatage.
- **Une remise à zéro des réglages est évitée** : la migration préserve modèle, classes,
  seuils, géométrie de détection et liste de plaques recherchées.
- **Le profil ANPR ne gagne rien**, et il faut le dire : mesuré à 17,2 puis 19,2 img/s
  sur la même fenêtre, il est très loin sous les 30 img/s du plafond, qui ne mordait
  donc jamais. Ce qui rend la vitesse normale atteignable avec l'ANPR n'est pas ce
  correctif mais **le pas d'analyse** (`frameStride`) : à pas 3 sur une source 60 fps,
  la période devient `3/60 = 50 ms`, soit 20 img/s analysées pour une scène qui avance
  à vitesse normale.
- **Une analyse sur une machine partagée peut désormais prendre tout ce qu'elle peut**
  si l'utilisateur choisit aussi « Cadence d'analyse : Illimitée ». C'est le
  comportement d'avant ADR 0022, et il reste un choix explicite en deux clics.

## Ce que la mesure a aussi montré, et qui n'est pas dans cette décision

La première course d'une session rend **29,6 img/s** là où la quatrième en rend 58,8,
sur la même vidéo et le même code. La trace `nvidia-smi` prise pendant les courses
donne la cause, et ce n'est pas le lot d'inférence :

| course | ordre | horloge SM p50 | débit |
|---|---|---|---|
| lot 4 | 1ʳᵉ | 885 MHz | 29,59 img/s |
| lot 8 | 2ᵉ | 1113 MHz | 32,66 img/s |
| lot 12 | 3ᵉ | 1518 MHz | 37,18 img/s |
| lot 2 | 4ᵉ | 1518 MHz | 53,21 img/s |

L'horloge monte de 885 à 1518 MHz au fil des courses — **1,72×**, ce qui explique
presque exactement le 1,80× de débit. Une comparaison de lots lue sur ce tableau
conclurait que « le lot 2 est 1,8× meilleur que le lot 4 » ; en courses **alternées sur
carte chaude**, le lot 4 rend 58,8 et le lot 2 rend 53,7 — l'inverse. Le choix d'ADR 0031
est donc confirmé, et le tableau ci-dessus ne mesure que la montée en horloge.

Deux conséquences pratiques, hors du périmètre de cette ADR :

- **toute mesure sur cette machine exige des courses alternées et répétées, carte déjà
  chaude.** Le `--warmup` du banc chauffe le *modèle*, pas la *carte* ;
- **le GPU n'est jamais saturé** : utilisation p50 de 44 à 56 %, pic à 72 %, sur les
  quatre courses. Le levier « donner plus de travail au GPU » n'a donc pas d'objet ici ;
  ce qui limite est la fraction CPU du pipeline et, en début de session, la gestion
  d'énergie du pilote.
