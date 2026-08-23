# ADR 0034 — La mesure de vitesse est retirée

- **Statut** : accepté
- **Date** : 2026-08-21
- **Abroge** [ADR 0025](0025-la-calibration-se-fait-par-ligne.md), dont il ne reste
  rien : ni calibration par ligne, ni champ d'échelle, ni conversion en km/h.

## Contexte

L'application mesurait une vitesse par véhicule et la publiait à trois endroits : la
colonne « Vitesse » du registre, deux colonnes de chaque export CSV, et un
`speedPxS` par piste dans les aperçus. Elle demandait pour cela deux réglages de
calibration — une échelle globale px/m dans « Affichage & analyse », une longueur
réelle par ligne dans « Géométrie » — dont le second était **le seul champ de ligne
que le serveur interprétait**, donc le seul dont la correction imposait une
réanalyse.

La fonctionnalité n'est plus voulue dans le produit.

## Décision

Retirer la vitesse **entièrement**, plutôt que la masquer :

- **domaine** : `domain/speed.py` et `domain/scale_field.py` sont supprimés, avec
  leurs tests. `SessionConfig.pixels_per_meter`, `CountingLineDef.length_m`,
  `TrackedObject.speed_px_s` et les deux champs `VehicleRecord.avg_speed_*`
  disparaissent ;
- **contrat** : `pixelsPerMeter` et `lengthMeters` quittent `AnalysisRequest`,
  `speedPxS` quitte `TrackSnapshot`, `avgSpeedPxS` / `avgSpeedKmh` quittent
  `VehicleRecord`, des deux côtés à la fois — les fixtures sont régénérées par
  `scripts/build_fixtures.py`, jamais éditées à la main ;
- **base** : `job_vehicles.avg_speed_px_s` et `avg_speed_kmh` sont supprimées par la
  migration `7c1f4b2ae903`. Rien à transposer, et le `downgrade` les recrée vides :
  une vitesse ne se recalcule pas sans le trajet, qui n'est pas persisté ;
- **interface** : le curseur « Échelle globale (px/m) », le champ « Longueur
  réelle » du panneau Géométrie, la colonne « Vitesse » du registre et sa note de
  bas de tableau, `formatSpeed`, et les deux colonnes des CSV.

## Conséquences

- **Une ligne n'a plus aucun champ que le serveur interprète.** Nom et rôles de sens
  ne font que traverser, donc **toute** correction du tracé est désormais
  instantanée : plus rien ne demande une réanalyse. C'est le seul gain de fond.
- **Les résultats archivés portent encore les anciennes clés** dans leur
  `result.json.gz`. Elles sont simplement ignorées à la relecture — aucun compteur
  n'en dépendait, contrairement au changement de sémantique d'ADR 0016.
- **Le repli honnête disparaît avec ce qu'il protégeait.** `formatSpeed` distinguait
  km/h, px/s et « — » précisément pour ne jamais inventer un chiffre ; la règle qui
  l'a motivé reste vraie de toute mesure dérivée qu'on rajouterait ici plus tard.
