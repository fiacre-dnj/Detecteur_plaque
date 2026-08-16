# ADR 0009 — Un véhicule compte une fois, la ré-identification ré-arme

- **Statut** : **abrogé** par [ADR 0016](0016-compter-les-objets-suivis.md) — son garde
  et toute la ré-identification qui lui servait de clé ont été supprimés du code. Reste
  ici pour l'histoire : il explique pourquoi le garde a existé, ce qui est ce dont on a
  besoin avant de le réintroduire.
- **Date** : 2026-08-07
- **Remplace** : la règle de déduplication `(ligne, identité, sens)` de
  [`prompt/03-DOMAINE-COMPTAGE.md`](../../prompt/03-DOMAINE-COMPTAGE.md) §3

## Contexte

Le compteur dédupliquait sur la clé **`(ligne, identité, sens)`**. Deux
conséquences, toutes deux voulues à l'époque et toutes deux fausses au regard de
la règle métier réelle :

1. **Plusieurs lignes multiplient le total.** Un véhicule qui traverse trois
   lignes tracées en travers de la même voie compte **3**. Or on trace plusieurs
   lignes pour *situer* un passage — entrée de carrefour, milieu, sortie — pas
   pour le compter trois fois. L'utilisateur qui pose une seconde ligne voit son
   total doubler sans qu'aucun véhicule de plus soit passé.
2. **Un aller-retour compte 2.** Le sens faisait partie de la clé précisément
   pour cela.

Ce n'était pas un bug : les docstrings, `prompt/03` §3 et le tableau des tests
obligatoires l'affirmaient explicitement, et deux tests s'opposaient
délibérément pour maintenir le compromis. C'est une **spécification** qui
change, d'où cette ADR.

## Décision

**Une identité compte une fois, point** — quelle que soit la ligne, quel que
soit le sens. Le compteur n'est **ré-armé** que par une vraie
ré-identification, et le ré-armement redonne droit à exactement **un**
franchissement de plus.

La clé de déduplication devient **`(identité, génération)`**, où la génération
est `SessionTrack.reid_count` : le nombre de ré-identifications déjà subies par
l'identité.

### Les trois arbitrages

| Question | Décision | Pourquoi |
|---|---|---|
| Aller-retour sur la même ligne | **1** | Le véhicule n'est jamais parti. Un demi-tour devant la caméra n'est pas un second passage. |
| Ce qui ré-arme | **toute vraie ré-identification** | Les deux chemins qui incrémentent déjà `reid_hits` : `reacquire()` (id de piste ressuscité) et `Admission.reidentified` (appariement d'apparence). Tous deux supposent que le véhicule a réellement disparu plus de `max_lost_ms`. |
| Détail par ligne | **première ligne servie** | `by_line[première].total = 1`, les suivantes restent à `0`. |

### Pourquoi « première ligne servie » et non « détail complet, total unique »

L'alternative — laisser chaque ligne compter son vrai total et ne publier qu'un
`crossings` global de 1 — casse l'invariant fondateur
`crossings == Σ by_line[*].total`, et avec lui trois choses qui en dérivent :

- `observe()` ne rendrait plus *seulement* les franchissements comptabilisés, ce
  qui fait mentir le badge ✓ (piège 2 de `prompt/13`) ;
- le rejeu frontend (`statsAt`, `replay.ts`) recalcule toutes les statistiques
  en rejouant les événements : il divergerait du backend ;
- deux totaux vivraient en parallèle, exactement ce que l'invariant 3 interdit.

L'arbitrage retenu ne coûte rien de tout cela : **aucune ligne de code frontend
n'a été modifiée**, et c'est la suite de tests du navigateur, passée telle
quelle, qui le prouve.

## Implémentation

Un seul fichier de production :
`backend/src/traffic_analysis/features/counting/domain/line_counter.py`.

- `_LineState` perd `counted_directions` et ne garde que de la géométrie
  (`side`, `pending_direction`). Ce garde portait sur la **piste** ; le laisser
  aurait été pire que redondant, car `_state` n'est purgé nulle part et il aurait
  bloqué le recomptage d'une piste ressuscitée sous le **même `track_id`** — le
  cas de ré-identification le plus fréquent.
- `_tally` n'a plus qu'un refus : `(global_id, reid_count)` déjà vu.
- `counted_identities()` accumule les générations, donc **le ✓ ne se rétracte
  jamais** : un véhicule ré-identifié reste marqué compté en attendant de
  recroiser.

Le compteur **lit** `track.reid_count` au lieu de recevoir un appel `rearm()` de
la session. La session a déjà arrêté l'identité de chaque piste dans
`_resolve_identities`, qui s'exécute avant `observe()` : aucun nouveau contrat
d'ordre n'est introduit dans un fichier qui en documente déjà l'ordre comme
« le contrat ».

## Conséquences

- Les totaux baissent sur toute configuration multi-lignes. C'est le but, mais
  une comparaison avec une analyse antérieure n'a plus de sens.
- Le **taux de franchissement** de l'écran de résultats devient enfin lisible
  comme « part des véhicules uniques qui ont franchi une ligne ». Il peut encore
  dépasser 100 %, mais désormais pour une seule raison : les ré-identifications.
- Le plafond des invariants se resserre de `uniques × lignes × 2` à
  `uniques + ré-identifications`. L'ancien restait vrai avec le garde débranché ;
  le nouveau ne le peut pas.
- `job_crossings` n'a toujours **aucune contrainte d'unicité**, mais pour une
  autre raison : ce n'est plus l'aller-retour qu'il faut laisser coexister, c'est
  le second passage d'un véhicule ré-identifié sur la même ligne.
