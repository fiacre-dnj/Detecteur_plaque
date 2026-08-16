# 03 — Le domaine du comptage (spécification normative)

Ce fichier est la partie la plus importante du prompt. Chaque règle énoncée ici
a coûté un bug dans la version précédente : la reproduire, c'est éviter de le
repayer. Tout ce module est **pur** — pas de FastAPI, pas d'ultralytics, pas de
SQLAlchemy, pas d'horloge murale.

## 0. Invariants transverses

1. **Toutes les coordonnées sont en pixels de la vidéo source.**
2. **Tous les temps sont des millisecondes de scène** : `frame_index / fps ×
   1000`. Côté serveur c'est vrai *par construction* — ne jamais introduire
   `time.time()` dans un calcul métier.
3. **Un compteur affiché est dérivé du détail.** `crossings` = Σ `byLine[*].total`.
   Ne jamais accumuler les deux en parallèle.
4. **On compte sous `identity_label`** (vote majoritaire de la galerie), jamais
   sous la lecture de la frame courante.
5. **Le badge « compté » (✓) dérive du tally**, jamais de la comptabilité
   interne d'une piste.

---

## 1. `domain/geometry.py` — la référence de la convention de sens

```python
@dataclass(frozen=True, slots=True)
class Point:
    x: float
    y: float

def side_of_line(a: Point, b: Point, p: Point) -> int:
    """Côté signé de p par rapport à la ligne orientée a→b : -1, 0 ou +1."""
    cross = (b.x - a.x) * (p.y - a.y) - (b.y - a.y) * (p.x - a.x)
    return 1 if cross > 0 else (-1 if cross < 0 else 0)
```

- **La direction d'un franchissement est le signe du côté d'arrivée.** `+1` et
  `−1` sont exposés tels quels dans l'API et libellés « A→B » / « B→A » dans
  l'UI. Cette convention est *le* contrat partagé avec le frontend : il l'utilise
  pour afficher les flèches du registre.
- `segments_intersect(p1, p2, p3, p4)` : vrai seulement si les deux segments se
  croisent réellement (test des quatre orientations,
  `d1 != d2 and d3 != d4`).
  **Pourquoi c'est indispensable** : le seul changement de signe bascule sur la
  ligne **infinie**. Un véhicule qui passe bien au-delà des extrémités tracées
  changerait de côté sans jamais couper le segment, et serait compté.
- `point_in_polygon(point, polygon)` : lancer de rayon, gère les polygones
  **concaves** (une voie tracée à la main l'est presque toujours). Faux si moins
  de 3 sommets.
- `distance(a, b)` : `math.hypot`.

Tests obligatoires : signe de part et d'autre, `0` sur la ligne, segments
sécants vs colinéaires vs disjoints, point dans un polygone concave en U,
point exactement sur une arête (comportement documenté et figé).

---

## 2. `domain/models.py` — le vocabulaire

```python
@dataclass(frozen=True, slots=True)
class BoundingBox:
    x: float; y: float; width: float; height: float
    @property
    def centroid(self) -> Point: ...

@dataclass(frozen=True, slots=True)
class TrackObservation:      # ce que le moteur rapporte pour une frame
    track_id: int; class_id: int; label: str; score: float; box: BoundingBox

@dataclass(frozen=True, slots=True)
class CountingLineDef:
    id: str; name: str; a: Point; b: Point; zone_id: str | None = None

@dataclass(frozen=True, slots=True)
class ZoneDef:
    id: str; name: str; points: tuple[Point, ...]

@dataclass(frozen=True, slots=True)
class VideoInfo:
    width: int; height: int; fps: float; frame_count: int
    @property
    def duration_ms(self) -> float: ...

@dataclass(frozen=True, slots=True)
class CrossingEvent:
    line_id: str; global_id: int; track_id: int; label: str
    direction: int          # +1 | -1
    timestamp_ms: float; frame_index: int

@dataclass(frozen=True, slots=True)
class ZoneEntryEvent:
    zone_id: str; global_id: int; label: str
    timestamp_ms: float; frame_index: int

@dataclass(frozen=True, slots=True)
class PlateDetection:
    box: BoundingBox; score: float

@dataclass(slots=True)
class SessionTrack:          # état VIVANT, muté frame après frame
    track_id: int; class_id: int; label: str; score: float
    box: BoundingBox; centroid: Point
    previous_centroid: Point | None = None
    hits: int = 0
    global_id: int = 0             # 0 tant que la galerie n'a pas tranché
    reid_count: int = 0
    identity_label: str = ""       # vote majoritaire — le label de comptage
    counted: bool = False          # écrit par la session depuis le tally
    last_seen_ms: float = 0.0
    speed_px_s: float | None = None
    plates: list[PlateDetection] = field(default_factory=list)

    def snapshot(self) -> SessionTrack: ...
```

### `snapshot()` n'est pas une commodité, c'est une correction de bug
La session mute **la même instance** d'une frame à l'autre. Une timeline qui
stockerait la référence vivante verrait **toutes ses lignes converger vers
l'état final** : à la relecture, chaque frame afficherait la position finale des
véhicules. La timeline stocke donc des snapshots, pris **après** la passe ANPR
(sinon les plaques manquent), et `plates` est copié (`list(self.plates)`).

Agrégats de sortie :

```python
@dataclass(slots=True)
class LineTally:
    total: int = 0
    by_class: dict[str, int] = field(default_factory=dict)
    positive: int = 0          # sens A→B
    negative: int = 0

@dataclass(slots=True)
class ZoneTally:
    entries: int = 0           # entrées uniques, ne décroît jamais
    inside: int = 0            # occupation instantanée, réécrite chaque frame
    by_class: dict[str, int] = field(default_factory=dict)

@dataclass(frozen=True, slots=True)
class VehicleRecord:           # une ligne du registre
    global_id: int; label: str
    first_seen_ms: float; last_seen_ms: float
    crossed_lines: tuple[tuple[str, int, float], ...]   # (line_id, direction, ts)
    zones_visited: tuple[str, ...]
    reid_count: int
    avg_speed_px_s: float | None
    avg_speed_kmh: float | None
    best_plate_score: float | None

@dataclass(frozen=True, slots=True)
class AnalysisStats:
    unique_vehicles: int
    unique_by_class: dict[str, int]
    crossings: int
    by_class: dict[str, int]
    by_line: dict[str, LineTally]
    by_zone: dict[str, ZoneTally]
    reid_hits: int
    vehicles_per_minute: float
    active_tracks: int
    elapsed_ms: float
    analysed_scene_ms: float
```

---

## 3. `domain/line_counter.py` — comptage de franchissements

Classe `LineCrossingCounter(lines, zones, min_hits)`. Elle **détecte et
déduplique au même endroit**, et `observe()` ne rend que les événements qui ont
réellement atteint un compteur.

> **Abrogé par [ADR 0016](../docs/adr/0016-compter-les-objets-suivis.md) :
> il n'y a plus aucun garde de déduplication.** Le garde décrit ici comme
> `(ligne, identité, sens)` était devenu `(identité, génération)` sous
> [ADR 0009](../docs/adr/0009-un-comptage-par-vehicule.md), puis débranché par
> [ADR 0014](../docs/adr/0014-compter-des-passages.md), puis **supprimé** avec
> `reid_count` qui lui servait de clé.
>
> Ce qui vaut aujourd'hui : **chaque franchissement observé compte**. Un aller-retour
> compte 2, deux lignes en travers d'une même voie comptent 2, une occlusion qui coupe
> une piste compte 2. Le seul garde restant est **géométrique** : l'intersection de
> segments.
>
> `_tallied` existe encore, mais comme `set[int]` de numéros de véhicule et pour une
> seule raison : alimenter `counted_identities()`, source du badge ✓ et de
> `crossed_unique`.

État interne :
- `_state: dict[(track_id, line_id), _LineState]` où
  `_LineState(side: int = 0, pending_direction: int | None = None)` — de la
  géométrie seule, aucune comptabilité ;
- `_tallied: set[global_id]` — **plus un garde** : la source du badge ✓ ;
- `by_line: dict[str, LineTally]`.

### Algorithme de `observe(tracks, timestamp_ms, frame_index)`

Pour chaque piste, pour chaque ligne :

1. `confirmed = track.hits >= min_hits`.
2. **Émission différée** : si `state.pending_direction is not None and
   confirmed`, comptabiliser ce franchissement en attente, puis remettre à
   `None`.
3. `side = side_of_line(line.a, line.b, track.centroid)` ; si `side == 0`,
   passer (pile sur la ligne, on attend la frame suivante).
4. **Amorçage** : si `state.side == 0`, écrire `state.side = side` et **ne rien
   compter**. Une piste vue pour la première fois déjà au-delà d'une ligne n'a
   pas été *observée* la franchir.
5. Si `side == state.side`, rien à faire.
6. Sinon (changement de côté), vérifier **deux** conditions, toutes deux
   géométriques :
   - `in_zone` : si `line.zone_id` est renseigné, le centroïde doit être dans le
     polygone ;
   - `segments_intersect(previous_centroid or centroid, centroid, line.a, line.b)`.
   Si les deux sont vraies : comptabiliser si `confirmed`, sinon
   `state.pending_direction = side`. La déduplication n'est **pas** une de ces
   conditions : elle est décidée dans `_tally`, qui refuse en rendant `None`.
   Filtrer ici sur ce qui a déjà compté remettrait un garde sur la piste, que
   l'occlusion efface.
7. **`state.side = side` est écrit même quand le franchissement est rejeté.**
   Sans cela, une piste rejetée « regarde dans le mauvais sens » et le
   franchissement suivant compte à l'envers.

### `_tally(...)`
- un seul refus : clé `(track.global_id, track.reid_count)` — **si déjà dans
  `_tallied`, rien n'atteint le compteur**. Peu importe que ce soit sur une autre
  ligne, dans l'autre sens, ou sous une piste depuis longtemps détruite : c'est le
  même véhicule, il a déjà compté ;
- label = `track.identity_label or track.label` ;
- incrémente `total`, `by_class[label]`, et `positive`/`negative` ;
- émet un `CrossingEvent`.

`counted_identities()` rend `{global_id for (global_id, _) in _tallied}` : c'est
la source du badge ✓. Les générations s'accumulent, donc **le ✓ ne se rétracte
jamais** — un véhicule ré-identifié reste marqué compté en attendant de
recroiser.

### Pourquoi ces règles (à conserver dans les docstrings)
- Sans le report `min_hits`, **tout véhicule qui franchit dans ses premières
  frames est perdu** — cas fréquent d'une ligne tracée près du bord de l'image.
  Sans le report *mais avec* le comptage immédiat, une seule boîte parasite à
  cheval sur la ligne devient un véhicule.
- Sans le garde d'identité, un véhicule qui franchit, disparaît 15 frames et
  revient avec une boîte qui tremble sur la ligne **compte 2**.
- Ni la ligne ni le sens n'entrent dans la clé : plusieurs lignes en travers
  d'une même voie servent à *situer* un passage, pas à le multiplier, et un
  demi-tour devant la caméra n'est pas un second passage.
- Seule une **vraie** ré-identification ré-arme, parce que `reid_count`
  n'augmente que lorsqu'un véhicule réellement disparu est reconnu à son retour.

### Tests obligatoires
| Scénario | Attendu |
|---|---|
| Piste traversant le segment, confirmée | 1 événement, `direction` correct |
| Piste passant au-delà des extrémités (ligne infinie franchie) | 0 |
| Piste apparaissant déjà de l'autre côté | 0 |
| Aller-retour complet | **2** — un par sens (ADR 0016) |
| Tremblement sur la ligne dans le même sens | **2** — deux franchissements observés |
| Franchissement pendant `hits < min_hits`, piste ensuite confirmée | 1, émis à la confirmation |
| Idem mais piste qui meurt avant confirmation | 0 |
| Deux pistes successives au même endroit | **2** — on compte des passages |
| Une piste qui traverse deux lignes successives | **2**, une sur chaque ligne |
| Ligne liée à une zone, franchissement hors zone | 0, **et** `state.side` mis à jour (le franchissement suivant dans l'autre sens compte correctement) |
| `crossings` = Σ `by_line[*].total`, et `total` = `positive.total + negative.total` | toujours vrai, désormais **par construction** (propriétés dérivées) |
| Chaque `global_id` compté figure au registre | toujours vrai — remplace l'ancien plafond `unique_vehicles + reid_hits`, disparu avec `reid_hits` |
| `by_class` et `first_ms`/`last_ms` **par sens** | ventilés séparément, la matrice type × sens |

---

## 4. `domain/zone_counter.py` — présence en zone

Classe `ZonePresenceCounter(zones, min_hits)` avec
`_inside: dict[(track_id, zone_id), bool]`, `_entered: set[(zone_id, global_id)]`
et `by_zone: dict[str, ZoneTally]`.

Pour chaque zone, pour chaque piste :
1. `inside = point_in_polygon(track.centroid, zone.points)` ; si `inside`,
   incrémenter le compteur d'occupation **de cette frame**.
2. **Report `min_hits`** : si `inside and track.hits < min_hits`, `continue`
   **sans écrire `_inside`**. Consommer le front dehors→dedans pendant la montée
   en confiance perdrait silencieusement l'entrée.
3. Lire `previous = _inside.get(key)`, écrire `_inside[key] = inside`.
4. Émettre une entrée seulement si `previous is False` (donc `previous is not
   None`, `inside` vrai, `previous` faux). Une piste déjà dedans à sa première
   évaluation amorce l'état sans émettre.
5. Déduplication par `(zone_id, global_id)` : un véhicule qui sort puis revient
   n'est **pas** une seconde entrée.
6. Après la boucle des pistes : `tally.inside = inside_now` — **une lecture, pas
   une accumulation**.

Tests : entrée simple ; piste née dedans ; sortie puis retour (1 entrée,
occupation qui varie) ; piste non confirmée qui entre puis se confirme
(l'entrée est bien émise) ; polygone concave.

---

## 5. ~~`domain/reid.py` — ré-identification longue durée~~ — **ABROGÉ**

> **Cette section entière est abrogée par
> [ADR 0016](../docs/adr/0016-compter-les-objets-suivis.md).** `domain/reid.py` est
> supprimé : plus de descripteur d'apparence, plus d'appariement, plus de budget de
> déplacement, plus de `ReidOptions`.
>
> Il est remplacé par `domain/track_numbering.py`, qui fait deux choses et rien
> d'autre : **numéroter** les pistes du tracker (numéro local à la session, jamais
> réattribué — voir le piège 60 pour la raison) et **voter la classe** (vote majoritaire
> sur la vie du véhicule, à égalité duquel le tenant garde la place). Le vote est
> **repris tel quel** de `IdentityGallery.vote` ci-dessous : la règle était juste, c'est
> la ré-identification autour qui ne l'était pas.
>
> Le reste de cette section est conservé pour l'histoire — il explique ce que la galerie
> faisait, ce dont on aurait besoin avant de la réintroduire.

## 5 (historique). `domain/reid.py` — ré-identification longue durée

BoT-SORT maintient l'identité à travers les occlusions **courtes**
(`track_buffer`). Au-delà, l'id de piste change et le véhicule serait compté
comme neuf. La galerie donne une **identité globale** qui survit à la
disparition : c'est elle qui distingue « véhicules uniques » de « passages ».

### Le descripteur (64 valeurs)
- Crop de la boîte **rogné de 10 % par côté** (`CROP_INSET_RATIO = 0.1`) : les
  coins d'une boîte de détection sont surtout du fond.
- Refus si `width < 20 px` ou `height < 20 px`, ou si le crop rogné est plus
  petit que 16×16 → **signature `None`**.
- Vignette **16×16** par moyenne de blocs (`_mean_pool`). *Historique : elle
  était 8×8, chaque cellule moyennant un patch 2×2 — à peine au-dessus du bruit,
  assez instable pour que des retours légitimes échouent, chaque échec devenant
  une identité neuve et un second franchissement. En 16×16, une cellule moyenne
  16 pixels pour le même coût.*
- Contenu : grille **4×4 de moyennes RGB** (48 valeurs) + **histogramme de teinte
  16 bins pondéré par la saturation** (16 valeurs). La pondération évite que le
  bitume et les vitres (pixels gris) votent pour un bin arbitraire.
- **Centrage avant normalisation L2** : toutes les composantes sont des
  intensités positives, donc sans centrage deux véhicules **sans rapport**
  scorent déjà ~0,7 et la plage utile du cosinus s'écrase. Mesuré après
  centrage : même objet 1.00, objets différents ≈ 0,01.
- `aspect = width / height` est stocké à côté du descripteur.

### Options (`ReidOptions`) — valeurs et raisons
| Champ | Défaut | Raison |
|---|---|---|
| `min_similarity` | **0.80** | Trop haut : un véhicule qui revient devient un **véhicule unique de plus** (son second passage compterait de toute façon, cf. ADR 0009 — c'est le décompte des uniques qui dérive). Trop bas : deux sosies fusionnent et le second n'est jamais compté. Exposé dans l'UI |
| `class_mismatch_penalty` | 0.12 | Volontairement **petite** : car/bus/truck sont réellement confondus par le détecteur et doivent rester appariables |
| `aspect_penalty_weight` | 0.30 | C'est **ceci** qui sépare les classes : une moto (~0,7) et une voiture (~1,5) donnent une pénalité ~0,25, assez pour mettre l'identité d'une voiture hors de portée d'une moto |
| `min_gap_ms` | **0.0** | Le tracker détruit une piste morte et crée sa remplaçante dans le *même* appel : un écart minimum non nul refuserait le match légitime |
| `max_gap_ms` | 30 000 | 30 s de **footage** |
| `signatures_per_entry` | 5 | Plusieurs points de vue par identité |
| `refresh_every_frames` | 8 | Coût maîtrisé de la mise à jour d'apparence |
| `max_travel_ratio` | 0.35 | Fraction de la diagonale de l'image par `travel_reference_ms` |
| `travel_reference_ms` | 200 | Référence du gate de déplacement |

### Structure d'une entrée
`_Entry(global_id, votes: dict[label, (class_id, count)], class_id, label,
signatures: list, active_track_id: int | None, last_seen_ms, last_centroid,
reid_count)`.

### Règles d'appariement (`admit_batch(candidates, now_ms, frame_diagonal)`)
1. **Élagage** (`_prune`) : les entrées non portées et plus vieilles que
   `max_gap_ms` sont retirées — elles ne pouvaient plus matcher et ne faisaient
   qu'allonger chaque scan. **Mais les compteurs cumulés restent** : `size` et
   `count_by_class()` sont des compteurs d'émission (`_issued_count`,
   `_issued_by_class`), pas une vue de `entries`. Les véhicules élagués restent
   comptés.
2. **Éligibilité** : `active_track_id is None` — une identité portée par une
   piste vivante n'est pas une réapparition (deux voitures identiques à l'écran
   restent deux) — et `min_gap_ms ≤ now - last_seen ≤ max_gap_ms`.
3. **Gate de déplacement** (`_can_reach`) *avant* tout scoring :
   `budget = frame_diagonal × max_travel_ratio × (max(gap, ref) / ref)` ;
   si `distance(candidat, entry.last_centroid) > budget`, rejet.
   **Sans ce gate**, une voiture rouge qui entre en haut de l'image hérite de
   l'identité d'une voiture rouge sortie en bas, et le vrai second véhicule n'est
   jamais compté.
4. **Score** = `max` de la similarité sur les signatures stockées (le **meilleur**
   point de vue, pas leur moyenne) − `class_penalty` − `aspect_penalty_weight ×
   |ln(aspect_candidat / aspect_stocké)|`.
5. **Glouton best-first** : tous les couples `(score, candidat, entrée)` au-dessus
   de `min_similarity`, triés par score décroissant ; un candidat et une entrée
   ne sont pris qu'une fois. Deux arrivées ne peuvent pas revendiquer la même
   identité.
6. Un match incrémente `reid_count` et `hits` (compteur global) ; les candidats
   non appariés — dont **tous ceux à signature `None`** — reçoivent une identité
   neuve. Deviner sur du bruit est pire que créer une identité.

### `vote(global_id, class_id, label)`
Vote majoritaire cumulé. **Une égalité laisse le tenant en place** : une lecture
qui alterne bus/camion ne fait jamais osciller un véhicule entre deux compteurs.
Quand la majorité change, `_retally` déplace le vote unique de l'identité d'un
total de classe à l'autre, donc `count_by_class()` somme toujours à `size`.

### `release(global_id, now_ms, centroid)`
**`now_ms` doit être l'instant où le véhicule a réellement été vu pour la
dernière fois**, jamais celui de la destruction de la piste. La piste ne meurt
qu'après avoir « planté » `max_lost_ms` ; dater le release à « maintenant »
sous-estime l'écart de jusqu'à 2,5 s, affame le budget de déplacement, rejette
le retour légitime — qui devient une identité neuve et un second comptage.

### `reacquire(global_id, track_id, now_ms, centroid)`
Re-lie une identité à une piste qui la porte encore (reconnue par id).
**Seule une vraie récupération** — identité relâchée, non portée — incrémente
`reid_count` et `hits`. Re-lier une identité déjà vivante est de la tenue de
registre, pas une ré-identification ; le compter ferait mentir la carte
« Ré-identifications ».

### Tests obligatoires
Même objet ≈ 1.0 / objets différents ≈ 0.01 ; boîte < 20 px → `None` ;
identité vivante inéligible ; gate de déplacement qui rejette un saut
impossible ; glouton qui n'attribue pas deux fois la même identité ;
moto qui n'hérite pas de l'identité d'une voiture ; camion relu comme voiture
qui **retrouve** son identité ; `count_by_class()` somme à `size` après un
changement de majorité ; élagage qui ne fait pas baisser `size`.

---

## 6. `domain/speed.py` — vitesse par identité

- Par identité : dernier centroïde + dernier horodatage, EMA `alpha = 0.3`
  (une boîte qui tremble d'un pixel ne doit pas faire osciller la vitesse
  affichée), et cumul `total_distance_px` / `total_duration_ms` pour la moyenne.
- Un trou `> 1000 ms` de scène (occlusion, ré-identification lointaine) ne décrit
  pas un déplacement continu : **on ré-amorce** sans intégrer.
- `to_kmh(px_s)` rend `None` si `pixels_per_meter` est absent ou ≤ 0.
  **Honnêteté avant tout** : sans échelle fournie par l'utilisateur, la vitesse
  reste en px/s ; la convertir en km/h serait une invention.

---

## 7. `domain/tracking_session.py` — la composition, une frame à la fois

`AnalysisSession(config: SessionConfig, frame_width, frame_height)` où
`SessionConfig(lines, zones, mask_outside_zones, min_hits, max_lost_ms=2500,
pixels_per_meter, reid: ReidOptions)`.

La **même** session sert le fichier différé et le flux temps réel : c'est tout
l'intérêt du découpage.

### `feed(frame_index, timestamp_ms, image, observations) -> FrameOutcome`

Ordre **impératif** :

```
1. kept = _mask(observations)                  # filtre zones si mask_outside_zones
2. active = _advance_tracks(kept, timestamp_ms)
3. _release_lost(timestamp_ms)                 # RELÂCHER…
4. _resolve_identities(active, image, ts)      # …AVANT D'ADMETTRE
5. crossings  = counter.observe(active, ts, frame_index)
6. zone_events = zones.observe(active, ts, frame_index)
7. counted = counter.counted_identities()
   for t in active: t.counted = t.global_id != 0 and t.global_id in counted
8. for t in active: t.speed_px_s = speed.observe(t.global_id, t.centroid, ts)
9. _aggregate(active, crossings, zone_events, ts)
```

- **Étape 1 — `_mask` avant le suivi, jamais après.** Avec
  `mask_outside_zones`, les zones sont la région d'intérêt : une détection en
  dehors ne devient jamais une piste, donc les voitures en stationnement et le
  parking dans un coin de l'image ne coûtent rien et n'entrent jamais dans un
  compteur. Sans le masque, une zone n'est qu'un filtre de comptage.
- **Étapes 3 et 4 — release avant admit.** Le moteur détruit une piste morte et
  crée sa remplaçante dans le même appel ; relâcher les identités *après*
  `admit_batch` laisse l'ancienne identité marquée vivante exactement quand sa
  remplaçante la demande, l'exclusivité refuse le match et le véhicule est admis
  comme neuf. Mesuré avec l'ancien ordre : 2 véhicules uniques et 0
  ré-identification ; avec le bon : 1 et 1.
- **Étape 7 — le ✓ dérive du tally.** Un franchissement supprimé par le garde
  d'identité ne doit pas peindre ✓ (le compteur n'a pas bougé) ; une
  ré-identification doit le conserver.
- `_release_lost` parcourt **toutes** les pistes connues (pas seulement les
  actives) et relâche celles dont `timestamp_ms - last_seen_ms > max_lost_ms`,
  en datant le release de `last_seen_ms` et en passant le dernier centroïde.
  L'id relâché est mémorisé dans `_released_ids`.
- `_resolve_identities` : les pistes à `global_id == 0` deviennent des
  `ReidCandidate` (signature extraite du crop) et passent par `admit_batch` ;
  les pistes déjà identifiées votent (`vote`) et rafraîchissent leur apparence
  une frame sur `refresh_every_frames`. Si une piste dont l'identité avait été
  relâchée réapparaît avec **le même `track_id`** (BoT-SORT peut ressusciter un
  id), c'est une **récupération par id** : `reacquire`, puis retirer l'id de
  `_released_ids`.

### `record_plates(track, plates)`
Attache les plaques à la piste et met à jour `best_plate_score` de l'agrégat
d'identité. Appelée par le service **après** `feed` et **avant** le snapshot.

### `stats()`
- `crossings` et `by_class` **dérivés** de `by_line` ;
- `analysed = last_ts - first_ts` ;
- `vehicles_per_minute = crossings / analysed × 60000` **seulement si**
  `analysed ≥ 3000 ms`, sinon `0.0` : en dessous de 3 s de flux,
  l'extrapolation du débit oscille trop pour être publiable ;
- `unique_vehicles = gallery.size`, `unique_by_class = gallery.count_by_class()`,
  `reid_hits = gallery.hits` ;
- côté serveur, `elapsed_ms == analysed_scene_ms` (le temps « écoulé » **est** le
  temps de scène analysé). Le champ reste dans le contrat parce que le frontend
  affiche les deux.

### `vehicles()`
Un `VehicleRecord` par identité agrégée, trié par `global_id`, avec le label
**du vote** (`gallery.label_of`), la vitesse moyenne px/s et sa conversion km/h
si l'échelle existe.

### Tests obligatoires de la session
Ils utilisent des `TrackObservation` fabriquées à la main (aucun moteur) :
1. Un véhicule qui traverse : 1 unique, 1 franchissement, ✓ posé.
2. Un véhicule occulté 3 s puis revenu au même endroit : **1 unique**, ≥ 1
   `reid_hits`, et **1** franchissement s'il ne recroise pas.
2 bis. Le même, mais qui **recroise** la ligne en remontant : toujours **1
   unique**, ≥ 1 `reid_hits`, et **2** franchissements — la ré-identification a
   ré-armé le comptage (ADR 0009). C'est le pendant du test 2 : sans lui, un
   véhicule faisant la navette resterait invisible après son premier passage.
3. Deux véhicules identiques simultanés : 2 uniques (exclusivité).
4. `mask_outside_zones` : une observation hors zone ne crée aucune piste.
5. Une piste dont la lecture alterne bus/camion : `identity_label` stable,
   `unique_by_class` sommant à `unique_vehicles`.
6. `stats()` : cohérence `crossings == Σ by_line.total`, débit nul sous 3 s.
7. Timeline : deux frames consécutives ont des snapshots **différents**
   (non-régression du piège d'aliasing).

---

## 8. `application/analysis_service.py` — l'orchestration

```python
VEHICLE_CLASS_IDS = (2, 3, 5, 7)   # car, motorcycle, bus, truck — traitées à l'identique

@dataclass(frozen=True, slots=True)
class AnalysisJobConfig:
    model_id: str
    confidence_threshold: float = 0.35
    iou_threshold: float = 0.45
    min_hits: int = 2
    mask_outside_zones: bool = False
    frame_stride: int = 1
    detect_plates: bool = False
    pixels_per_meter: float | None = None
    reid_min_similarity: float = 0.80
    max_lost_ms: float = 2500.0
    lines: tuple[CountingLineDef, ...] = ()
    zones: tuple[ZoneDef, ...] = ()
    def engine_spec(self) -> EngineSpec: ...
    def session_config(self) -> SessionConfig: ...
```

`run_video(video_path, config, on_progress=None, is_cancelled=None)` :
bloquant, **exécuté dans un thread worker** par le `JobManager`.

```
info = engine.probe(path)
session = AnalysisSession(config.session_config(), info.width, info.height)
for frame in engine.iter_video(path, config.engine_spec()):
    if is_cancelled and is_cancelled(): raise AnalysisCancelled
    outcome = session.feed(frame.frame_index, frame.timestamp_ms, frame.image, frame.tracks)
    if config.detect_plates and plates is not None:
        for track in outcome.tracks:
            session.record_plates(track, plates.detect(frame.image, track.box))
    timeline.append(TimelineRow(frame.frame_index, frame.timestamp_ms,
                                tuple(t.snapshot() for t in outcome.tracks)))  # APRÈS l'ANPR
    crossings += outcome.crossings ; zone_events += outcome.zone_events
    processed += 1
    if on_progress and processed % 10 == 0: on_progress(Progress(...))
result.processing_fps = processed / elapsed
result.vehicles = session.vehicles() ; result.stats = session.stats()
on_progress(final)                      # la barre doit atteindre 100 %
```

- `total = frame_count // stride` : la progression doit être en unités
  d'images **analysées**, sinon la barre plafonne à `1/stride`.
- `AnalysisCancelled` est une annulation, **pas une erreur** : le `JobManager`
  la traduit en statut `cancelled`.
- La progression est publiée toutes les 10 frames analysées : plus souvent, on
  noie le SSE ; moins souvent, la barre paraît figée.

## 9. Mémoire — la limite à connaître

Une timeline de 30 min à 30 fps compte 54 000 lignes ; à 8 pistes moyennes cela
fait ~430 000 snapshots. C'est acceptable en RAM le temps du job (dataclasses
`slots`), mais **le résultat sérialisé doit être écrit en `json.gz` sur disque**,
jamais gardé en mémoire après la fin du job (voir
[`07-PERSISTANCE-SQLITE.md`](07-PERSISTANCE-SQLITE.md)). Si `frame_count × 1
/ stride > 200 000`, journaliser un avertissement et suggérer un `frameStride`
supérieur dans la réponse du job.
