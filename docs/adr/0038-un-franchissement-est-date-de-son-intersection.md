# ADR 0038 — Un franchissement porte la date de son intersection, pas de sa preuve

- **Statut** : accepté
- **Date** : 2026-08-25
- **Complète** [ADR 0018](0018-une-bande-morte-autour-du-trait.md) — et *complète*, pas
  *amende* : la bande morte reste, le rattrapage
  d'[ADR 0023](0023-un-vehicule-compte-est-un-vehicule-qui-franchit.md) reste, **aucun
  comptage ne change**.

## Le symptôme

« Je veux que le comptage lors du franchissement soit plus instantané ; parfois le
comptage a un peu de retard après le passage, même si on compte bien les passages. »

La formulation est exacte et c'est ce qui la rend utile : les totaux sont justes, seule
leur date ne l'est pas.

## La cause, et elle était documentée

ADR 0018 entoure chaque trait d'une **bande morte** d'un quart de demi-boîte, dans laquelle
le côté d'une piste n'est pas tranché. C'est ce qui a supprimé les doublons d'un véhicule
arrêté sur un trait, et cela reste juste.

Mais le compteur datait le franchissement de l'instant où il pouvait le **prouver** — la
sortie de bande — et non de celui où il avait eu lieu. `CLAUDE.md` le disait déjà en toutes
lettres : « mesuré jusqu'à **2,2 s** de retard pour un gros véhicule abordant une ligne
presque parallèlement. Le comptage est juste, sa date est tardive. »

Le retard n'est pas constant, et c'est ce qui le rend visible : la bande a une épaisseur
**proportionnelle à la boîte** (`0,125 × max(largeur, hauteur)`), soit ±15 px pour une
voiture et ±50 px pour un poids lourd. Un camion au premier plan compte donc nettement plus
tard qu'une moto au même endroit.

ADR 0018 avait nommé le remède et posé sa condition :

> Le remède existe et n'a pas été retenu ici : mémoriser l'instant de l'intersection réelle
> comme *candidat*, puis l'émettre — avec sa date d'origine — une fois la bande franchie.
> Il déplace le problème sur l'ordre d'émission des événements. À reprendre si la date d'un
> passage devient un usage à part entière.

**La condition est remplie.** Depuis le 2026-08-17, le registre affiche « Entrée par » et
« Sortie par » au dixième de seconde, et la chronologie en dérive `gapMs`, le numéro de
passage et le **temps de traversée du carrefour**.

## La décision

Le compteur retient, à **chaque** image observée — y compris dans la bande morte —
l'**écart signé** au trait, son instant et son index. Quand le signe bascule entre deux
images, il retient l'instant **interpolé** de l'intersection. À la sortie de bande, `_tally`
reçoit cet instant à la place de l'instant courant.

La séparation tient en une phrase : **le côté tranché décide s'il faut compter, l'écart
brut dit quand c'est arrivé.**

Trois points qui ne se devinent pas :

- **l'écart signé et non le côté.** `signed_line_offset` rend un flottant ; c'est lui qui
  permet d'interpoler au lieu de rabattre sur une frontière d'image. Sur un pas de 40 ms,
  la différence entre « au quart » et « au milieu » est de 10 ms, et le registre affiche le
  dixième de seconde ;
- **le dernier basculement gagne, pas le premier.** C'est la sémantique déjà écrite d'ADR
  0018 — un véhicule qui frémit sur le trait « en produira un quand il repartira, du côté
  où il repart ». Retenir le premier daterait un aller-retour de son premier frémissement ;
- **`_tally` ne change pas d'une ligne.** Il recevait déjà `timestamp_ms` en paramètre :
  c'est l'appelant qui décide. Aucune condition d'acceptation n'est touchée.

### Pourquoi c'est inattaquable, et pourquoi aucun garde n'est nécessaire

L'instant retenu est toujours dans `]t(image précédente), t(image courante)]` —
l'intervalle pendant lequel le franchissement s'est **prouvablement** produit. La date
d'aujourd'hui est la **borne supérieure** de cet intervalle, prise plusieurs images plus
tard. Le nouveau calcul ne peut donc jamais être moins juste : il remplace une borne
supérieure lointaine par un point de l'intervalle.

Deux inquiétudes naturelles, toutes deux levées par le code existant :

- **« un franchissement daté d'avant l'existence du véhicule »** ferait passer
  `crossedUnique` au-dessus de `trackedVehicles` en relecture. Impossible :
  `_number_tracks` émet le numéro dès la **première** image de la piste, donc
  `first_seen_ms` date de la première apparition — et il faut deux images pour interpoler ;
- **« une date périmée réutilisée »**. Un `_tally` de l'étape 4 exige un changement de côté
  *tranché*, ce qui implique au moins un basculement brut entre deux `_tally`. La date
  consommée est donc toujours postérieure au précédent. La remise à `None` après
  consommation et à l'amorçage rend cette propriété vérifiable plutôt que déductible.

## L'objection d'ADR 0018, et ses trois réponses

« Il déplace le problème sur l'ordre d'émission des événements. » C'est exact, et c'est le
seul vrai coût. La bande étant proportionnelle à la boîte, **deux véhicules peuvent être
comptabilisés dans l'ordre inverse de leur passage réel**.

1. **`DirectionTally.record` prend `min` / `max`** au lieu de « première » et « dernière
   écriture ». Sans quoi un sens pourrait rendre `first_ms > last_ms`, indéfendable pour
   deux champs nommés ainsi. Même correction dans le miroir client, `replay.ts` `tallyLine`.
2. **`result.crossings` est trié** après la boucle, sur `(instant, image, ligne, véhicule)`
   — les trois clés secondaires pour que deux courses du même fichier rangent deux passages
   simultanés de la même façon. `pending_crossings` est trié de la même façon **par trame
   SSE**. Le tri vit dans l'**application** et non dans le domaine : le compteur émet au fil
   de l'eau et n'a aucune raison de connaître l'ordre final.
3. **`appendCrossings` insère en gardant le journal trié** au lieu d'empiler. C'est ce qui
   referme le désordre *entre* deux trames SSE, que le serveur ne peut pas voir. Sans cela,
   `previous.deltaMs` — le temps de traversée du carrefour — deviendrait négatif. Coût borné
   par la limite du journal : au pire 200 comparaisons par trame.

**La base de données avait anticipé** : `sqlalchemy_repository` trie déjà par
`timestamp_ms, id`. Rien à y faire.

## Ce que cela change, chiffré sur la fixture du contrat

Régénérée par `build_fixtures.py` — jamais éditée à la main :

| | avant | après |
|---|---|---|
| `crossings[0].timestampMs` | 240,0 | **200,0** |
| `crossings[0].frameIndex` | 6 | **5** |
| `crossings[1].timestampMs` | 280,0 | **240,0** |
| `byLine[*].byDirection[*].firstMs` | 240,0 / 280,0 | **200,0 / 240,0** |
| `crossings`, `byLine[*].total`, `trackedVehicles` | — | **identiques** |

Une image de gain sur une scène synthétique à 40 ms. Sur une vraie ligne quasi parallèle à
une voie, le gain attendu se compte en secondes — c'est le chiffre à relever contre le
vrai serveur (voir plus bas) et à mettre en face des 2,2 s d'ADR 0018.

Les tests du domaine ont bougé aux valeurs exactes prédites : `120,0 → 80,0`,
`140,0` à la place de la frame de confirmation, `120,0 → 100,0` pour `first_ms`. **Tous les
tests de `TestBandeMorte`, `TestIdentifiantDePisteRecycle` et `TestQuasiFranchissements`
sont inchangés** — c'est la propriété centrale : aucun compte ne bouge.

## Les résultats archivés

Un résultat archivé n'est pas réanalysé et **ne change pas** : ses dates restent celles de
la sortie de bande. Il ne devient pas faux — le comptage était et reste juste — il est
simplement daté à l'ancienne. Aucune clé n'est ajoutée ni retirée, donc aucun ne cesse de
se relire.

Comparer deux analyses du même clip, avant et après, montre **les mêmes totaux et les mêmes
lignes, à des secondes différentes**.

## Comment le vérifier

Le contrôle qui compte, contre le vrai serveur :

1. analyser **deux fois le même clip, même tracé**, avant et après. `stats.crossings`,
   chaque `byLine[*].total` et chaque `byDirection` doivent être **identiques au chiffre
   près**. Si un total bouge, le changement a débordé sur la décision de compter et doit
   être repris ;
2. comparer les `crossings[i].timestampMs` deux à deux, et relever gain moyen et gain
   maximal ;
3. se placer à `crossings[i].timestampMs` dans la barre de lecture, sur la ligne la plus
   parallèle à une voie : le centroïde du véhicule doit être **sur le trait**, pas déjà
   loin derrière ;
4. `uv run python scripts/audit_lignes.py` avant et après : les lignes à zéro le restent,
   les quasi-franchissements aussi.
