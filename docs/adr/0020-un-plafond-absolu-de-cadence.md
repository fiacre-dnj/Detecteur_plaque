# ADR 0020 — Un plafond absolu de cadence, indépendant du temps de la scène

- **Statut** : accepté
- **Date** : 2026-08-16
- **Complète** : [ADR 0017](0017-brider-l-analyse-sur-le-temps-de-la-scene.md) et
  [ADR 0019](0019-la-lecture-locale-reste-a-vitesse-normale.md) — sans rien leur
  retirer, ni changer leur défaut.

## Contexte

`analysisSpeed` (ADR 0017, défaut « temps réel » depuis ADR 0019) borne la
cadence d'analyse **relativement** à la vidéo : « 1× » veut dire « pas plus vite
que cette source ne défile », quelle que soit sa cadence propre. C'est le bon
réglage pour que la lecture locale reste normale.

Ce n'est pas le même besoin que « ne jamais dépasser N images par seconde »
**dans l'absolu**, indépendamment de la source. Demandé explicitement :
brider le débit du serveur lui-même à 30 (ou 60) images par seconde — par
exemple pour partager une machine entre plusieurs analyses sans que celle sur
une source à 60 fps consomme deux fois plus de débit que celle sur une source à
30 fps.

## Décision

`maxAnalysisFps` (nouveau, `max_analysis_fps` côté serveur) borne le débit de
l'analyse en images par seconde **réelle**, sans référence à la cadence de la
source. `null` — le défaut — n'impose aucune borne, comme `analysisSpeed` avant
ADR 0019 : ce plafond est un choix supplémentaire, pas une correction, donc il ne
s'active pas tout seul.

Les deux réglages sont **indépendants et composables** : `ScenePacer.for_video`
calcule les deux périodes possibles et retient la plus longue (`domain/pacing.py`).
Trois différences qui ne se devinent pas :

- **`maxAnalysisFps` ignore `frame_stride`.** `analysisSpeed` en tient compte —
  avec un pas de 3, chaque image analysée fait avancer la scène de trois images,
  et cadencer sur le nombre d'images analysées brimerait l'analyse au tiers de la
  vitesse demandée. `maxAnalysisFps` compte des images analysées, pas du temps de
  scène couvert : le pas n'y intervient pas ;
- **`maxAnalysisFps` fonctionne même quand la source ne déclare pas sa cadence**
  (`fps <= 0`), contrairement à `analysisSpeed` qui ne sait alors pas ce que
  « temps réel » voudrait dire. Une source défensivement mal formée peut donc
  quand même être plafonnée dans l'absolu ;
- **aucun des deux n'est prioritaire** : c'est arithmétiquement la période la plus
  longue qui gagne, donc le réglage le plus restrictif des deux, quel qu'il soit.

L'interface propose deux valeurs, comme les cadences relatives : « 30 img/s » et
« 60 img/s », les deux cadences vidéo courantes — pas un curseur continu qui
inviterait à régler un chiffre arbitraire. Bornes serveur : `[1 ; 240]`.

## Conséquences

- Aucun compteur ne change : c'est le même mécanisme d'attente entre deux images
  qu'ADR 0017, verrouillé par le même test
  (`test_le_bridage_ne_change_aucun_chiffre`), qui ne distingue pas la source du
  bridage.
- Le journal d'une analyse bridée porte désormais `analysis_speed` **et**
  `max_analysis_fps`, pour qu'un débit inattendu se diagnostique sans deviner
  lequel des deux régnait.
- Sans effet en direct, comme `analysisSpeed` — c'est le client qui cadence son
  envoi.
