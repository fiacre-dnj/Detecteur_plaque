"""Comptage de franchissements de lignes.

**Chaque franchissement observé compte.** Il n'y a plus de garde de
déduplication : `dedupe_by_identity`, dernier vestige d'ADR 0009, a été supprimé
par ADR 0016 en même temps que la ré-identification qui lui donnait sa clé. Un
aller-retour compte 2, deux lignes en travers d'une même voie comptent 2, et une
occlusion qui coupe une piste en deux compte 2.

`observe()` ne rend que les événements qui ont réellement atteint un compteur —
ce qui, désormais, est tous ceux qu'il détecte. La propriété est conservée parce
que c'est elle qui permet au badge ✓ de l'interface de dériver du tally plutôt que
de la comptabilité d'une piste, et parce qu'elle laisse la porte ouverte à un
futur refus sans avoir à rebrancher l'overlay.

Le compteur tient enfin un **diagnostic** — `near_misses()` — et pas un second
comptage : les pistes qui se sont éteintes à portée d'une ligne sans jamais la
franchir. C'est ce qui distingue une ligne que personne n'emprunte d'une ligne mal
placée, deux situations qui affichent le même `0` et appellent des gestes opposés.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from traffic_analysis.features.counting.domain.geometry import (
    Point,
    point_segment_distance,
    segments_intersect,
    signed_line_offset,
)
from traffic_analysis.features.counting.domain.models import (
    CountingLineDef,
    CrossingEvent,
    LineTally,
    SessionTrack,
    ZoneDef,
)
from traffic_analysis.features.counting.domain.zone_geometry import track_is_in_zone

if TYPE_CHECKING:
    from collections.abc import Container, Iterable, Sequence


#: Seuil du **quasi-franchissement**, exprimé en demi-boîtes du véhicule.
#:
#: `1.0` signifie « la boîte du véhicule recouvrait encore la ligne quand la piste
#: s'est éteinte ». Le seuil est relatif à la boîte et non en pixels, pour la raison
#: qui vaut partout ailleurs dans ce projet : un plancher absolu réglé sur du 720p
#: ne veut plus rien dire en 4K, alors qu'une demi-boîte décrit la même situation
#: physique à toute résolution.
NEAR_MISS_RATIO = 1.0

#: Demi-épaisseur de la **bande morte** autour d'un trait, en demi-boîtes.
#:
#: Dans cette bande, le côté d'une piste n'est pas tranché : c'est le traitement que
#: le compteur réservait déjà au centroïde tombant *exactement* sur la ligne, avec
#: une épaisseur mesurée au lieu de zéro.
#:
#: **Le zéro coûtait des doublons.** Mesuré sur `video_7.mp4` : un véhicule arrêté
#: sur un trait pendant 0,4 s a produit **trois** franchissements comptés, aux
#: distances +0,1 / −0,1 / +0,2 px — le signe du produit vectoriel bascule sur du
#: bruit numérique. Un second cas, où la boîte du détecteur s'effondre puis se
#: rétablit (demi-boîte 69 → 47 → 38 → 61 px), a déplacé le centre de quelques
#: pixels et donné trois passages de plus.
#:
#: `0.25` est un compromis mesuré des deux côtés, et les deux bornes ont été
#: touchées :
#:
#: - **plancher** — le bruit observé plafonne à **0,10** demi-boîte, donc 2,5× de
#:   marge. En dessous, les doublons reviennent ;
#: - **plafond** — la bande est traversée *avant* d'être franchie, donc trop large
#:   elle avale des trajets entiers. À `0.5`, un poids lourd de 400 px obtient une
#:   bande de 100 px, et le scénario de non-régression du doublon cabine/remorque —
#:   120 px de trajet — cessait d'être compté. Ce test a rejeté la valeur.
#:
#: Relatif à la boîte et non en pixels, pour la raison habituelle : un plancher
#: absolu réglé en 720p ne veut plus rien dire en 4K. Et pour une raison propre à ce
#: cas : le bruit dominant est **proportionnel** à la boîte — une boîte qui perd 30 %
#: de son étendue déplace son centre d'environ 15 % de cette étendue.
#:
#: Ce n'est **pas** un garde d'identité. Il ne regarde ni le numéro du véhicule, ni
#: les autres lignes, ni ce qui a déjà été compté : un aller-retour franc compte
#: toujours 2, et deux lignes franchies comptent toujours 2. Voir ADR 0018.
CROSSING_BAND_RATIO = 0.25


def _near_miss_ratio(track: SessionTrack, line: CountingLineDef) -> float:
    """Distance du centroïde au segment, **en demi-boîtes du véhicule**.

    `1.0` veut dire « la boîte touchait encore la ligne ». C'est la mesure qui
    correspond à ce que l'utilisateur voit : à l'écran il juge sur la boîte, pas
    sur le centroïde, et c'est tout l'écart entre « cette voiture est passée
    dessus » et « son centre n'a jamais changé de côté ».

    Une boîte dégénérée rend `inf` — jamais un quasi-franchissement, parce qu'un
    objet sans surface ne permet aucun jugement.
    """
    half_extent = max(track.box.width, track.box.height) / 2.0
    if half_extent <= 0.0:
        return float("inf")
    return point_segment_distance(track.centroid, line.a, line.b) / half_extent


@dataclass(slots=True)
class _LineState:
    """Ce que le compteur retient d'un triplet (piste, véhicule, ligne).

    Aucune comptabilité ici — de la géométrie seule.

    **La clé porte le numéro de véhicule en plus de l'identifiant de piste**, et
    ce n'est pas une précaution théorique : sans lui, un `track_id` réémis par le
    tracker pour un *autre* véhicule héritait du côté et de la dernière position
    du précédent. Le segment testé reliait alors le dernier point du véhicule A
    au premier point du véhicule B — un bond qui traverse le trait — et le
    compteur émettait un **franchissement fantôme** pour un véhicule qui n'avait
    rien franchi. Mesuré : véhicule A qui longe la ligne par le haut, véhicule B
    qui naît en dessous, aucun des deux ne franchit, et le total montait à 1.
    C'est le mode de panne le plus coûteux en trafic dense, où les occlusions
    tuent et ressuscitent les pistes en permanence.

    L'état reste **jamais purgé** dans sa fenêtre : une piste réactivée sous
    `max_lost_ms` garde son `global_id`, donc sa clé, donc sa mémoire — la raison
    d'origine (piège 11 de prompt/13, « ne pas repartir en amorçage ») est
    intégralement préservée. Au-delà, la session donne un numéro neuf, et repartir
    en amorçage est alors le comportement **juste** : c'est un autre véhicule.

    Borné par le nombre de pistes du clip, pas par sa durée.
    """

    # Dernier côté **tranché** — c'est-à-dire observé hors de la bande morte. `0`
    # signifie « pas encore amorcé » : une piste vue pour la première fois n'a pas
    # de côté précédent, donc rien à comparer.
    side: int = 0
    # Dernière position **hors de la bande**, et non la position de l'image
    # précédente. C'est elle qui forme le segment testé contre le trait.
    #
    # Sans cette mémoire, la bande morte perdrait les franchissements qu'elle est
    # censée assainir : un véhicule qui s'arrête sur la ligne puis repart aurait,
    # au moment où il ressort de la bande, une image précédente **du même côté que
    # lui** — le segment ne couperait donc rien et le vrai franchissement
    # disparaîtrait. Le segment doit enjamber la bande, pas s'arrêter à son bord.
    settled_centroid: Point | None = None
    # Franchissement détecté alors que la piste n'était pas encore confirmée.
    # Il est mis en attente, pas jeté : le jeter perdrait tout véhicule qui
    # franchit dans ses premières frames — fréquent avec une ligne près du bord.
    pending_direction: int | None = None
    # **La date de ce franchissement en attente, portée avec lui.** Relire
    # `crossing_ms` au moment de l'émission serait faux : l'étape 5 a pu l'écraser
    # entre-temps, et l'événement porterait l'instant d'un autre basculement.
    pending_ms: float | None = None
    pending_frame: int = 0
    # Écart **signé** au trait de l'image précédente, avec son instant et son index.
    #
    # Le flottant et non le signe : c'est lui qui permet d'**interpoler** l'instant
    # de l'intersection au lieu de le rabattre sur une frontière d'image. Le signe
    # seul obligerait à repartir des centroïdes et à refaire la même arithmétique.
    #
    # Tenu à **chaque** image observée, y compris dans la bande morte — c'est
    # justement là que le franchissement a lieu, et la bande n'existe que pour
    # retarder la *décision*, jamais l'*observation*.
    raw_offset: float | None = None
    raw_ms: float = 0.0
    raw_frame: int = 0
    # Instant **interpolé** du dernier basculement de côté de la *droite* (sans
    # bande morte), et l'image qui le précède. C'est la date qu'un franchissement
    # portera, à la place de l'instant de sa sortie de bande. `None` = jamais
    # observé, et l'émission retombe alors sur l'instant courant.
    crossing_ms: float | None = None
    crossing_frame: int = 0
    # Ce couple a-t-il déjà fait bouger un compteur ? **Ce n'est pas un garde** —
    # rien ne le lit pour refuser un franchissement (ADR 0016). Il ne sert qu'au
    # diagnostic : une piste qui a franchi n'est jamais un quasi-franchissement.
    crossed: bool = False
    # Distance de la **dernière** position observée au segment, en demi-boîtes du
    # véhicule. La dernière et non la plus petite : la question posée est « la piste
    # s'est-elle éteinte à portée de la ligne ? », pas « est-elle passée près un
    # jour ? ». Un véhicule qui longe la ligne puis s'éloigne finit loin, et n'a
    # rien d'un franchissement manqué.
    last_ratio: float = float("inf")
    # Dernière position vue **avant tout amorçage**, avec son côté de la *droite*
    # (sans bande morte). Ces deux champs ne servent qu'une fois, et ils rattrapent
    # un franchissement que la bande morte faisait disparaître en silence.
    #
    # Le cas : une piste qui **naît dans la bande**. Elle n'a pas de côté tranché,
    # donc l'étape 2 renonce ; à l'image suivante, la voici franchement d'un côté,
    # et l'étape 3 s'en sert comme *amorçage* — le franchissement est perdu, alors
    # que les deux positions encadrent le trait. Ce n'est pas un cas de laboratoire :
    # la bande vaut un quart de demi-boîte, soit ±50 px pour un poids lourd de
    # 400 px, et toute piste qui apparaît dans cette fenêtre — véhicule entrant dans
    # le champ près du trait, piste recréée après une occlusion — était muette.
    #
    # Le côté **brut** et non tranché : dans la bande, c'est la seule information
    # disponible. Elle ne sert jamais à *compter* seule — il faut en plus une
    # intersection de segments franche — donc le bruit qui a motivé la bande morte
    # (ADR 0018) ne peut pas la déclencher : un véhicule qui frémit autour du trait
    # revient toujours du côté d'où il vient, et les côtés égaux ne comptent rien.
    origin_side: int = 0
    origin_centroid: Point | None = None


class LineCrossingCounter:
    """Compte **chaque franchissement observé**, ventilé par ligne et par sens.

    Un seul garde subsiste, et il est purement géométrique :
    **l'intersection de segments**. Sans lui, un véhicule qui passe au-delà des
    extrémités tracées serait compté, parce qu'il change de côté de la droite
    *infinie* — c'est le piège 7 de prompt/13.

    Le garde d'identité d'ADR 0009 a disparu avec la ré-identification (ADR 0016).
    Ses conséquences, désormais assumées :

    - un aller-retour compte **2**, une fois dans chaque sens ;
    - un véhicule qui franchit deux lignes compte sur **chacune**, ce qui est ce
      qu'on attend d'un carrefour où deux rues sont instrumentées séparément ;
    - une occlusion plus longue que `track_buffer` coupe la piste et donne **2**.

    `crossings == Σ by_line[*].total` reste vrai, parce que le total global est
    *dérivé* des tallies de lignes et jamais accumulé à côté (invariant 3).
    """

    __slots__ = ("_lines", "_min_hits", "_state", "_tallied", "_zones", "by_line")

    def __init__(
        self,
        lines: Sequence[CountingLineDef],
        zones: Sequence[ZoneDef],
        min_hits: int,
    ) -> None:
        self._lines = tuple(lines)
        self._zones = {zone.id: zone for zone in zones}
        self._min_hits = min_hits
        # Clé : (identifiant de piste, numéro de véhicule, ligne). Voir `_LineState`
        # — le numéro de véhicule est ce qui empêche un `track_id` recyclé d'hériter
        # de la géométrie du véhicule précédent et d'émettre un fantôme.
        self._state: dict[tuple[int, int, str], _LineState] = {}
        # Les véhicules ayant fait bouger un compteur. **La source du badge ✓**, et
        # sa seule raison d'exister depuis qu'il n'y a plus de déduplication :
        # cesser de le remplir ferait disparaître le ✓ de l'overlay, ce qui se
        # lirait comme une panne de comptage.
        self._tallied: set[int] = set()
        # Chaque ligne a son compteur dès le départ : une ligne sans
        # franchissement doit s'afficher à zéro, pas manquer du tableau.
        self.by_line: dict[str, LineTally] = {line.id: LineTally() for line in self._lines}

    def observe(
        self,
        tracks: Iterable[SessionTrack],
        timestamp_ms: float,
        frame_index: int,
    ) -> tuple[CrossingEvent, ...]:
        """Fait avancer le compteur d'une frame.

        Ne rend que les franchissements **effectivement comptabilisés**.
        """
        events: list[CrossingEvent] = []
        for track in tracks:
            confirmed = track.hits >= self._min_hits
            for line in self._lines:
                self._observe_line(track, line, confirmed, timestamp_ms, frame_index, events)
        return tuple(events)

    def counted_identities(self) -> set[int]:
        """Numéros de véhicule ayant réellement fait bouger un compteur.

        C'est la **source du badge ✓** et celle de `crossed_unique` — les deux
        répondent à la même question, « ce véhicule est-il passé ? », et les faire
        dériver de deux endroits finirait par afficher un ✓ sur un véhicule que le
        taux ne compte pas.

        Le ✓ ne se rétracte **jamais** : un numéro entré ici y reste jusqu'à la fin
        de la session.
        """
        return set(self._tallied)

    def near_misses(self, ignore: Container[int] = ()) -> dict[str, int]:
        """Pistes **éteintes à portée d'une ligne sans l'avoir franchie**, par ligne.

        Le chiffre qui explique une ligne à zéro. Sans lui, une ligne que personne
        ne franchit et une ligne mal placée affichent le même `0`, et le second cas
        se lit comme une panne du comptage — c'est exactement le diagnostic qui a
        coûté une demi-journée sur `video_7.mp4`, où trois pistes mouraient à ~33 px
        d'une ligne tracée à 60 px du bord de l'image.

        Ce **n'est pas** un compteur de franchissements et ne s'additionne à aucun
        total : c'est une mesure de la géométrie du tracé, pas du trafic. Un
        quasi-franchissement ne dit rien de ce qui s'est réellement passé à l'écran
        — le véhicule a peut-être franchi, peut-être fait demi-tour, peut-être
        stationné. Il dit seulement que **le tracé et le suivi se sont manqués de
        peu**, ce qui est actionnable : reculer la ligne, ou tenir la piste plus
        longtemps.

        `ignore` reçoit les identifiants de piste **encore vivants** : une piste qui
        approche de la ligne à l'instant où l'on publie n'a pas manqué son
        franchissement, elle ne l'a pas encore fait. Sans ce filtre, l'aperçu live
        annoncerait un quasi-franchissement par véhicule en approche, puis le
        retirerait — un chiffre qui clignote ne se lit pas.

        **Dérivé, jamais accumulé** (invariant 3) : recalculé depuis `_state` à
        chaque appel, donc il ne peut pas diverger de ce que le compteur a vu. Le
        coût est en `pistes × lignes` — quelques milliers d'itérations sur un clip
        long, contre une inférence par image.
        """
        counts = {line.id: 0 for line in self._lines}
        for (track_id, _global_id, line_id), state in self._state.items():
            if state.crossed or track_id in ignore:
                continue
            if state.last_ratio <= NEAR_MISS_RATIO:
                counts[line_id] = counts.get(line_id, 0) + 1
        return counts

    def _observe_line(
        self,
        track: SessionTrack,
        line: CountingLineDef,
        confirmed: bool,
        timestamp_ms: float,
        frame_index: int,
        events: list[CrossingEvent],
    ) -> None:
        state = self._state.setdefault((track.track_id, track.global_id, line.id), _LineState())

        # 0. Mémoire du diagnostic, tenue à **chaque** image observée — donc avant
        #    les trois retours anticipés ci-dessous. Les écrire après perdrait
        #    précisément le cas qu'on cherche à voir : la piste qui s'éteint pile
        #    sur la ligne, dont la dernière image repart en `side == 0`.
        if not state.crossed:
            state.last_ratio = _near_miss_ratio(track, line)

        # 0-bis. Mémoire de l'**instant** du franchissement, tenue à chaque image
        #        observée — donc, comme le diagnostic, avant les retours anticipés.
        #        Le compteur ne peut *prouver* un franchissement qu'à la sortie de
        #        bande, mais il peut le *dater* dès qu'il le voit : la bande morte
        #        décide de compter, elle n'a pas à décider quand. Voir ADR 0038.
        self._remember_crossing_instant(state, track, line, timestamp_ms, frame_index)

        # 1. Émission différée : la piste vient de se confirmer, et un
        #    franchissement l'attendait. Elle porte désormais un numéro — la
        #    session le lui a donné dans `_number_tracks`, juste avant `observe`.
        if state.pending_direction is not None and confirmed:
            events.append(
                self._tally(
                    track,
                    line,
                    state.pending_direction,
                    # **La date du franchissement, pas celle de la confirmation.**
                    # L'événement est émis quand la piste porte enfin un numéro ;
                    # il décrit un fait qui a eu lieu avant.
                    state.pending_ms if state.pending_ms is not None else timestamp_ms,
                    state.pending_frame if state.pending_ms is not None else frame_index,
                )
            )
            state.pending_direction = None
            state.pending_ms = None
            state.crossed = True

        # 2. Dans la bande morte : on ne tranche pas de côté et on attend une image
        #    où la piste est franchement d'un côté. C'est le traitement que ce code
        #    réservait au centroïde tombant *exactement* sur la ligne, avec une
        #    épaisseur mesurée au lieu de zéro — trancher au dixième de pixel
        #    produisait trois passages pour un véhicule arrêté sur le trait
        #    (ADR 0018). `settled_centroid` n'est **pas** mis à jour ici : c'est ce
        #    qui permet au segment de la sortie de bande d'enjamber le trait.
        side = self._settled_side(track, line)
        if side == 0:
            # Tant que la piste n'a pas de côté tranché, on retient sa dernière
            # position et le côté **brut** de la droite. C'est la seule mémoire qui
            # permette de rattraper, à la sortie de bande, le franchissement d'une
            # piste née dedans — voir `_LineState.origin_side`.
            if state.side == 0:
                offset = signed_line_offset(line.a, line.b, track.centroid)
                if offset != 0.0:
                    state.origin_side = 1 if offset > 0.0 else -1
                    state.origin_centroid = track.centroid
            return

        # 3. Amorçage : une piste vue pour la première fois déjà au-delà d'une
        #    ligne n'a pas été *observée* la franchir. On mémorise son côté et on
        #    ne compte rien — sinon chaque véhicule déjà passé au démarrage de
        #    l'analyse serait compté.
        if state.side == 0:
            state.side = side
            state.settled_centroid = track.centroid
            # **Sauf** si la piste est née dans la bande, du côté opposé à celui où
            # elle vient de se ranger : les deux positions encadrent alors le trait,
            # et le franchissement a bien été *observé*, simplement à cheval sur la
            # bande. Les mêmes deux conditions géométriques que l'étape 4 — portée et
            # intersection franche — donc rien de plus permissif qu'un franchissement
            # ordinaire, seulement une origine qu'on avait jetée.
            if (
                state.origin_side != 0
                and state.origin_side != side
                and state.origin_centroid is not None
                and self._crossing_is_in_scope(track, line)
                and segments_intersect(state.origin_centroid, track.centroid, line.a, line.b)
            ):
                self._emit_or_defer(
                    state, track, line, side, confirmed, timestamp_ms, frame_index, events
                )
            # **La mémoire d'intersection est effacée par tout amorçage**, qu'il ait
            # rattrapé un franchissement ou non : elle décrivait un instant où la
            # piste n'avait pas encore de côté tranché, donc elle ne peut pas dater
            # le franchissement *suivant*. Après la lecture, jamais avant.
            state.crossing_ms = None
            return

        if side == state.side:
            state.settled_centroid = track.centroid
            return

        # 4. Changement de côté : deux conditions **géométriques** doivent tenir.
        #    Le segment part de la dernière position **hors bande**, et non de
        #    l'image précédente : quand la piste vient de traverser la bande, sa
        #    position précédente est du même côté qu'elle, et le segment ne
        #    couperait rien.
        accepted = self._crossing_is_in_scope(track, line) and segments_intersect(
            state.settled_centroid or track.previous_centroid or track.centroid,
            track.centroid,
            line.a,
            line.b,
        )
        if accepted:
            self._emit_or_defer(
                state, track, line, side, confirmed, timestamp_ms, frame_index, events
            )
        state.crossing_ms = None

        # 5. Le côté est écrit **même quand le franchissement est rejeté**.
        #    Sans cela, la piste « regarde dans le mauvais sens » et son
        #    franchissement suivant compte à l'envers (piège 11 de prompt/13).
        state.side = side
        state.settled_centroid = track.centroid

    @staticmethod
    def _remember_crossing_instant(
        state: _LineState,
        track: SessionTrack,
        line: CountingLineDef,
        timestamp_ms: float,
        frame_index: int,
    ) -> None:
        """Retient **quand** la piste a traversé la droite, sans rien décider.

        La bande morte existe pour ne pas compter du bruit (ADR 0018), et elle fait
        très bien ce travail — mais elle datait aussi le franchissement de sa
        **sortie de bande**, mesurée jusqu'à 2,2 s après le trait pour un gros
        véhicule abordant une ligne presque parallèlement. Compter juste, dater
        tard : le registre et la chronologie s'en servent au dixième de seconde.

        La séparation est celle-ci : le côté **tranché** décide *s'il faut compter*,
        l'écart **brut** dit *quand c'est arrivé*. On interpole linéairement entre
        les deux images qui encadrent le changement de signe — la même hypothèse de
        vitesse constante que `segments_intersect` fait déjà pour accepter le
        franchissement.

        **Le dernier basculement écrase le précédent**, et c'est la sémantique déjà
        écrite d'ADR 0018 : un véhicule qui frémit sur le trait « en produira un
        quand il repartira, du côté où il repart ». Retenir le premier daterait un
        aller-retour de son premier frémissement.

        `previous * offset < 0.0` est **strict** : un écart exactement nul ne
        déclenche pas de basculement, la branche `offset == 0.0` s'en charge à
        l'image où il se produit, et `0.0 * x` n'étant jamais négatif, l'image
        suivante ne l'écrase pas.

        La première image d'une piste ne date rien : il n'y a rien à interpoler.
        """
        offset = signed_line_offset(line.a, line.b, track.centroid)
        previous = state.raw_offset
        if previous is not None:
            if previous * offset < 0.0:
                ratio = abs(previous) / (abs(previous) + abs(offset))
                state.crossing_ms = state.raw_ms + ratio * (timestamp_ms - state.raw_ms)
                # L'image qui **précède** l'intersection : l'instant retenu tombe
                # dans `[t(raw_frame), t(image courante)[`, donc `frameIndexAt` en
                # relecture — « dernière ligne dont l'instant ne dépasse pas » —
                # désigne exactement cette ligne-là.
                state.crossing_frame = state.raw_frame
            elif offset == 0.0:
                # Pile sur la droite : l'instant n'a pas à être estimé, il est là.
                state.crossing_ms = timestamp_ms
                state.crossing_frame = frame_index
        state.raw_offset = offset
        state.raw_ms = timestamp_ms
        state.raw_frame = frame_index

    def _emit_or_defer(
        self,
        state: _LineState,
        track: SessionTrack,
        line: CountingLineDef,
        direction: int,
        confirmed: bool,
        timestamp_ms: float,
        frame_index: int,
        events: list[CrossingEvent],
    ) -> None:
        """Compte maintenant, ou met en attente — avec **sa** date dans les deux cas.

        Les deux points d'acceptation (sortie de bande et rattrapage d'une piste née
        dans la bande) faisaient exactement le même choix, écrit deux fois. Les
        réunir n'est pas de la cosmétique : c'est ce qui garantit qu'ils datent leur
        événement de la même façon, et qu'un correctif sur l'un ne manque pas
        l'autre.

        Repli sur l'instant courant quand aucune intersection n'a pu être datée —
        boîte dégénérée, piste dont c'est la première image observée. C'est
        exactement le comportement d'avant, donc jamais une régression.
        """
        crossing_ms = state.crossing_ms if state.crossing_ms is not None else timestamp_ms
        crossing_frame = state.crossing_frame if state.crossing_ms is not None else frame_index
        if confirmed:
            events.append(self._tally(track, line, direction, crossing_ms, crossing_frame))
            state.crossed = True
        else:
            state.pending_direction = direction
            state.pending_ms = crossing_ms
            state.pending_frame = crossing_frame

    @staticmethod
    def _settled_side(track: SessionTrack, line: CountingLineDef) -> int:
        """Côté **tranché** de la piste : `0` tant qu'elle est dans la bande morte.

        La bande est exprimée en demi-boîtes du véhicule, donc son épaisseur en
        pixels suit la taille de l'objet : quelques pixels pour une voiture au
        loin, quelques dizaines pour un camion au premier plan. C'est ce qui la
        rend valable sur une même image comme d'une résolution à l'autre.

        Une boîte dégénérée retombe sur le test de côté strict — sans surface, il
        n'y a pas de demi-boîte, et refuser de trancher figerait la piste.
        """
        offset = signed_line_offset(line.a, line.b, track.centroid)
        half_extent = max(track.box.width, track.box.height) / 2.0
        if half_extent <= 0.0:
            return 0 if offset == 0.0 else (1 if offset > 0.0 else -1)
        if abs(offset) < CROSSING_BAND_RATIO * half_extent:
            return 0
        return 1 if offset > 0.0 else -1

    def _crossing_is_in_scope(self, track: SessionTrack, line: CountingLineDef) -> bool:
        """La ligne est-elle active à cet endroit pour cette piste ?

        Une ligne liée à une zone ne compte que ce qui traverse *dans* la zone :
        c'est ce qui permet de compter une seule voie d'un carrefour que la même
        ligne traverse deux fois.

        Une zone référencée mais absente laisse la ligne compter partout. Le cas
        est déjà refusé à la validation de l'API ; si une configuration ancienne y
        échappe, sous-compter en silence serait l'erreur la plus difficile à
        remarquer.
        """
        if line.zone_id is None:
            return True
        zone = self._zones.get(line.zone_id)
        if zone is None:
            return True
        return track_is_in_zone(track, zone)

    def _tally(
        self,
        track: SessionTrack,
        line: CountingLineDef,
        direction: int,
        timestamp_ms: float,
        frame_index: int,
    ) -> CrossingEvent:
        """Comptabilise un franchissement. **Le seul endroit qui fait bouger un total.**

        Il n'y a plus de refus possible : chaque franchissement géométriquement
        accepté est compté. La méthode reste séparée parce qu'elle est le point
        unique où un tally et un événement naissent ensemble — les faire naître à
        deux endroits laisserait l'overlay et les chiffres diverger.

        Le compteur écrit dans **un seul** objet, `LineTally.side(direction)` ; le
        total de la ligne et sa répartition par type en sont dérivés. C'est
        l'invariant 3 rendu structurel plutôt que surveillé.
        """
        self._tallied.add(track.global_id)

        label = track.counting_label
        self.by_line[line.id].side(direction).record(label, timestamp_ms)

        return CrossingEvent(
            line_id=line.id,
            global_id=track.global_id,
            track_id=track.track_id,
            label=label,
            direction=direction,
            timestamp_ms=timestamp_ms,
            frame_index=frame_index,
            # Le texte **voté** porté par la piste, jamais la lecture d'une frame :
            # le compteur ne sait pas qu'une OCR existe, il lit un champ. `None` et
            # non `""` — « pas encore lu » est une information, une chaîne vide
            # serait une plaque vide.
            plate_text=track.plate_text or None,
            plate_text_score=track.plate_text_score or None,
        )
