# ADR 0023 — Un véhicule compté est un véhicule qui franchit

- **Statut** : accepté
- **Date** : 2026-08-17
- **Amende** : [ADR 0016](0016-compter-les-objets-suivis.md) — son invariant
  « un objet suivi = un véhicule, ligne franchie ou non » cesse de gouverner ce
  que l'**écran** appelle un véhicule. Le comptage serveur, lui, ne change pas.
- **Complète** : [ADR 0018](0018-une-bande-morte-autour-du-trait.md), dont la
  bande morte avait un angle mort que cette ADR corrige.

## Contexte

Trois observations faites sur une même analyse réelle, écran à l'appui.

**1. Deux chiffres voisins qui ne se recoupent pas.** La Répartition affichait
`27 + 0 + 0 + 1 = 28` entrées, et juste dessous « Véhicules ayant traversé le
carrefour : **106** ». Les deux sont justes dans leur unité — le premier compte
des passages sur des sens « entrée », le second tout objet suivi confirmé — mais
posés l'un sous l'autre ils se lisent comme une contradiction. L'écart n'est pas
du bruit : il est fait de voitures en stationnement, de véhicules à l'arrêt dans
un coin du champ, et de pistes fragmentées par les occlusions. Aucune n'a
traversé quoi que ce soit.

**2. Le registre publiait ces mêmes objets.** `AnalysisSession.vehicles()` filtre
sur la seule confirmation de piste, donc le tableau comportait des lignes dont
« Lignes franchies » et « Passages » valaient « — ». Or le registre existe pour
rendre un total **vérifiable** : une ligne qu'on ne peut relier à aucun
franchissement n'est vérifiable par rien.

**3. La bande morte avalait des franchissements réels, et un identifiant recyclé
en inventait.** Deux défauts mesurés, de signes opposés, tous deux sur le
compteur de lignes — donc tous deux sur le KPI d'entrées :

- **sous-comptage** — une piste qui **naît dans la bande morte** n'a pas de côté
  tranché ; à l'image suivante, son premier côté tranché servait d'*amorçage* et
  le franchissement était perdu. La bande vaut un quart de demi-boîte, soit
  ±50 px pour un poids lourd de 400 px : tout véhicule entrant dans le champ près
  du trait, et toute piste recréée après une occlusion à cet endroit, tombait
  dedans. C'est le cas dominant en trafic dense, où les occlusions tuent et
  ressuscitent les pistes en permanence ;
- **sur-comptage** — `_LineState` était clé par `(track_id, ligne)` et n'est
  jamais purgé. Ultralytics **recycle** ses identifiants : au-delà de
  `max_lost_ms`, le même `track_id` désigne un autre véhicule, à qui la session
  donne un numéro neuf. Le compteur, lui, lui rendait le côté et la dernière
  position de l'occupant précédent. Le segment testé reliait alors le dernier
  point du véhicule A au premier point du véhicule B — un bond qui traverse le
  trait — et un **franchissement fantôme** était émis. Reproduit : deux véhicules
  dont aucun ne franchit, total de ligne à `1`.

## Décision

### Côté domaine — deux corrections du compteur

1. **Rattrapage à la sortie de bande.** Le compteur retient la dernière position
   observée avant tout amorçage et le côté **brut** de la droite. Si la piste se
   range du côté *opposé*, le franchissement est compté. Les deux conditions
   géométriques ordinaires restent exigées — portée de la ligne et intersection
   franche de segments — donc rien n'est plus permissif qu'un franchissement
   normal : seule une origine qu'on jetait est désormais lue.

2. **Le numéro de véhicule entre dans la clé d'état**, qui devient
   `(track_id, global_id, ligne)`. Une réactivation courte garde le même numéro,
   donc la même mémoire : la raison d'être d'un état non purgé (piège 11 de
   `prompt/13` — « ne pas repartir en amorçage et perdre le franchissement du
   retour ») est intégralement préservée. Un recyclage donne un numéro neuf, donc
   un amorçage — ce qui est le comportement **juste**, puisque c'est un autre
   véhicule.

### Côté interface — deux filtres, tous deux clients

3. **Le registre ne publie que les véhicules ayant franchi au moins une ligne**,
   tous sens confondus.

4. **« Véhicules ayant traversé le carrefour » compte les véhicules distincts
   entrés**, c'est-à-dire passés dans le sens « entrée » d'au moins une ligne.

Les deux prédicats vivent dans **un seul** module,
`results-dashboard/model/crossedVehicles.ts`, dérivés de
`VehicleRecord.crossedLines` — jamais d'un compteur parallèle (invariant 3).

## Pourquoi les filtres sont côté client, et non côté serveur

C'est le point qui a décidé de la forme de cette ADR.

Le serveur **ne lit jamais** les rôles de sens : il les accepte, les persiste
dans `config_json` et les rend, sans qu'aucun compteur les regarde (ADR 0016).
C'est ce qui rend le basculement d'un sens entrée ↔ sortie *instantané* — un mot
ne doit pas changer un chiffre du serveur, et corriger un rôle après coup ne
demande pas de relancer l'analyse.

Déplacer le filtre d'entrée côté serveur figerait les rôles dans le résultat
archivé : basculer un sens n'aurait plus d'effet sans réanalyser. La demande
d'origine étant précisément que **la détection d'entrée reste robuste au
basculement de sens**, le calcul client est la seule forme qui la satisfasse. Un
test le verrouille : le même franchissement archivé, deux rôles opposés, deux
verdicts.

Le filtre « a franchi une ligne » n'a pas cette contrainte — il ne dépend
d'aucun rôle — mais il reste client par cohérence : les deux sont le même geste,
et le serveur garde ainsi ses objets suivis complets, dont dépendent les
quasi-franchissements (`diagnostics.nearMisses`) et le script `audit_lignes.py`.

## Conséquences

- **`tracked_vehicles` ne change pas de sens côté serveur** ni dans l'API. Ce
  qui change, c'est ce que l'écran met en avant. `AnalysisSession.vehicles()`
  publie toujours tout véhicule confirmé, et c'est délibéré : sans stationnement
  dans le résultat, on ne peut plus diagnostiquer une ligne mal placée.
- **`len(vehicles()) == stats().tracked_vehicles` reste vrai côté serveur**, et
  cesse d'être vrai à l'écran. Les deux filtres sont nommés et testés ; la
  propriété serveur est celle qui compte pour le contrat.
- **Deux unités continuent de cohabiter et ne se divisent jamais** : un véhicule
  qui entre deux fois compte `1` dans « Véhicules ayant traversé » et `2` dans
  « Entrées au carrefour ». L'invariant 3 est intact — c'est même lui qui
  interdit de présenter le rapport des deux comme un taux.
- **Les totaux d'entrées bougent à la hausse comme à la baisse** sur une même
  vidéo réanalysée : le rattrapage de bande ajoute des franchissements réels, la
  clé par véhicule en retire des fantômes. Les deux effets sont indépendants et
  aucun ne compense l'autre.
- Un résultat archivé **n'a pas besoin d'être réanalysé** pour bénéficier des
  points 3 et 4 : ce sont des filtres d'affichage. Les points 1 et 2, eux, sont
  du comptage : ils demandent une nouvelle analyse.
