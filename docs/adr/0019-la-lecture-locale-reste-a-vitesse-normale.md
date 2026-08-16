# ADR 0019 — La lecture locale reste à vitesse normale par défaut

- **Statut** : accepté
- **Date** : 2026-08-16
- **Amende** : [ADR 0017](0017-brider-l-analyse-sur-le-temps-de-la-scene.md) — sans
  toucher au mécanisme de bridage, seulement à sa valeur par défaut.

## Contexte

ADR 0017 a donné à `analysisSpeed` un défaut à `null`, c'est-à-dire « aucune
borne » : le comportement historique, choisi pour que qui ne touche à rien garde
son débit d'analyse.

Mais l'aperçu live (ADR 0006) **cale** la balise `<video>` locale sur le temps de
scène de chaque échantillon analysé, il ne la lit pas. Sans borne, un GPU capable
de 50 à 60+ img/s sur une source à 25-30 fps fait donc défiler la vidéo locale
**plus vite que sa vitesse normale** — jusqu'à 1,7× mesuré en ADR 0017 — et cette
vitesse varie avec la charge instantanée du serveur : elle accélère et ralentit au
fil de l'analyse, sans qu'aucun réglage n'en soit la cause visible à l'écran.
Signalé par l'utilisateur : la lecture semble tantôt accélérée, tantôt ralentie,
« selon la vitesse d'analyse ».

Ce n'était pas un bug — c'était le défaut historique appliqué à du matériel plus
rapide que ce pour quoi il avait été choisi. Mais un défaut qui produit une vitesse
de lecture imprévisible n'est plus le bon défaut.

## Décision

`DEFAULT_SETTINGS.analysisSpeed` passe de `null` à `1` (« Temps réel »). C'est de
la lecture, pas du comptage :

- la vidéo locale défile à sa vitesse normale (0,99× mesuré en ADR 0017) tant que
  l'utilisateur ne touche à rien ;
- **aucun chiffre ne change** — le bridage n'ajoute qu'une attente entre deux
  images côté serveur, verrouillé par `test_le_bridage_ne_change_aucun_chiffre` ;
- l'analyse différée dure alors la durée de la vidéo plutôt que le temps que le
  serveur met à la traiter. « Illimitée » reste à un choix de l'écran pour qui veut
  ses chiffres au plus vite et accepte un aperçu qui accélère.

Le mécanisme de bridage, le rattrapage borné à trois périodes et les bornes
`[0,25 ; 8]` restent ceux d'ADR 0017, entièrement inchangés.

## Conséquences

- Une analyse différée sans réglage touché prend désormais environ la durée de la
  vidéo, plutôt que le temps de traitement du serveur — c'est le prix du confort de
  lecture, assumé.
- Un `localStorage` déjà écrit avec `analysisSpeed: null` explicite le reste : ce
  module ne réécrit que le défaut d'une installation neuve, jamais un choix déjà
  fait (`mergeSettings` ne retombe sur `DEFAULT_SETTINGS.analysisSpeed` qu'en
  l'absence totale du champ).
- Sans effet en direct, où c'est le client qui cadence son envoi (inchangé depuis
  ADR 0017).
