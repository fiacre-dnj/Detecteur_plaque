# ADR 0022 — Le plafond absolu vaut 30 img/s par défaut

- **Statut** : accepté
- **Date** : 2026-08-16
- **Amende** : [ADR 0020](0020-un-plafond-absolu-de-cadence.md) — sans toucher au
  mécanisme, seulement à sa valeur par défaut.

## Contexte

ADR 0020 a donné à `maxAnalysisFps` un défaut à `null`, c'est-à-dire « aucun
plafond » : un choix supplémentaire, pas un correctif, puisque la vitesse de
lecture normale était déjà assurée par `analysisSpeed` (ADR 0019).

Ce raisonnement reste vrai, mais laissait le réglage sans valeur par défaut
utile : `30 img/s` est la cadence vidéo la plus courante, et la poser par
défaut ne change rien pour qui filme à cette cadence ou en dessous — le
plafond n'est jamais atteint, donc jamais contraignant — tout en bornant
d'emblée le débit du serveur pour qui filme plus vite.

## Décision

`DEFAULT_SETTINGS.maxAnalysisFps` passe de `null` à `30`. « Illimité » et
« 60 img/s » restent des choix explicites dans le panneau, pour qui filme à
cadence plus élevée ou veut ses chiffres au plus vite sans égard pour le
partage de la machine.

## Conséquences

- Aucun compteur ne change — comme pour ADR 0020, ce plafond n'ajoute qu'une
  attente entre deux images.
- Une source à 30 fps ou moins n'est pas concrètement bridée par ce défaut :
  le plafond ne fait que **borner**, il n'accélère jamais une analyse qui va
  déjà à cette cadence ou moins.
- Une source plus rapide (caméra 60 fps, par exemple) est désormais bridée par
  défaut à 30 img/s, en plus du bridage relatif d'`analysisSpeed` — c'est le
  plus restrictif des deux qui s'applique (ADR 0020).
