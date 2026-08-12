"""Domaine → dictionnaires camelCase du fil.

Le résultat d'analyse est le **seul** objet servi sans validation pydantic : le
revalider doublerait la mémoire d'une timeline de plusieurs centaines de
mégaoctets pour rien. Son schéma est décrit à la main dans OpenAPI, et c'est ici
qu'il est produit.

Deux décisions de format, et toutes les deux se mesurent :

- **arrondir à la sérialisation** (4 décimales pour les scores, 1 pour les pixels
  et les millisecondes) divise la taille du JSON par près de deux sans rien
  perdre d'utile ;
- **`null` explicite plutôt qu'absent** pour une vitesse inconnue : `0` voudrait
  dire « à l'arrêt », et un champ absent obligerait le client à une branche
  conditionnelle par champ.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from traffic_analysis.features.counting.application.dto import (
        AnalysisResultData,
        TimelineRow,
    )
    from traffic_analysis.features.counting.domain.models import (
        AnalysisStats,
        BoundingBox,
        CrossingEvent,
        PlateDetection,
        SessionTrack,
        VehicleRecord,
        VideoInfo,
        ZoneEntryEvent,
    )

SCORE_DECIMALS = 4
PIXEL_DECIMALS = 1


def _score(value: float) -> float:
    return round(value, SCORE_DECIMALS)


def _pixel(value: float) -> float:
    return round(value, PIXEL_DECIMALS)


def _optional_pixel(value: float | None) -> float | None:
    return None if value is None else _pixel(value)


def serialise_box(box: BoundingBox) -> dict[str, float]:
    return {
        "x": _pixel(box.x),
        "y": _pixel(box.y),
        "width": _pixel(box.width),
        "height": _pixel(box.height),
    }


def serialise_plate(plate: PlateDetection) -> dict[str, Any]:
    """Une plaque sur le fil.

    `stale` est **omis quand il est faux** — exception assumée à la règle « `null`
    explicite » qui gouverne le reste de ce module, et pour la raison qu'ADR 0008
    donne déjà à propos des confiances par caractère : un booléen porté par 100 %
    des plaques de 45 000 images pèse sur chaque octet du `json.gz`, alors qu'il n'a
    de sens que dans le cas minoritaire. Le client le déclare donc `stale?`, et son
    absence signifie « mesurée sur cette image ».
    """
    payload: dict[str, Any] = {
        "box": serialise_box(plate.box),
        "score": _score(plate.score),
        # `null` explicite plutôt qu'absent : le client a une branche par
        # valeur, pas une branche par présence de clé.
        "text": plate.text,
        # `null` et non `0` quand rien n'a été lu : `0` dirait « lu, sans
        # aucune confiance », ce qui n'est pas la même information.
        "textScore": _score(plate.text_score) if plate.text else None,
    }
    if plate.stale:
        payload["stale"] = True
    return payload


def serialise_track(track: SessionTrack) -> dict[str, Any]:
    return {
        "trackId": track.track_id,
        "globalId": track.global_id,
        "classId": track.class_id,
        "label": track.label,
        # Le libellé voté est envoyé **en plus** de la lecture de la frame : le
        # canvas colore les boîtes par classe votée pour qu'une lecture qui
        # vacille ne fasse pas clignoter la couleur.
        "identityLabel": track.identity_label,
        "score": _score(track.score),
        "box": serialise_box(track.box),
        "hits": track.hits,
        "counted": track.counted,
        "reidCount": track.reid_count,
        "speedPxS": _optional_pixel(track.speed_px_s),
        "plates": [serialise_plate(plate) for plate in track.plates],
        # Le texte **voté**, en plus des lectures de la frame — même raison
        # qu'`identityLabel` : c'est lui que le canvas étiquette. Dessiner
        # `plates[].text` ferait clignoter l'étiquette, l'étranglement de l'OCR ne le
        # remplissant qu'une frame sur trois.
        "plateText": track.plate_text or None,
        "plateTextScore": _score(track.plate_text_score) if track.plate_text else None,
    }


def serialise_timeline_row(row: TimelineRow) -> dict[str, Any]:
    return {
        "frameIndex": row.frame_index,
        "timestampMs": _pixel(row.timestamp_ms),
        "tracks": [serialise_track(track) for track in row.tracks],
    }


def serialise_crossing(event: CrossingEvent) -> dict[str, Any]:
    return {
        "lineId": event.line_id,
        "globalId": event.global_id,
        "trackId": event.track_id,
        "label": event.label,
        # La catégorie voyage avec l'événement : la relecture côté navigateur
        # ventile par catégorie au fil de la tête de lecture, et la lui faire
        # deviner depuis le libellé lui ferait recopier la politique du serveur.
        "category": event.category,
        "direction": event.direction,
        "timestampMs": _pixel(event.timestamp_ms),
        "frameIndex": event.frame_index,
        # Ce que le serveur savait de la plaque **au moment de compter**. Souvent
        # `null` alors que le registre porte le texte, et c'est normal : les
        # franchissements sortent de `feed()` avant la passe OCR de la même frame.
        # L'autorité est le registre (ADR 0007).
        "plateText": event.plate_text,
        "plateTextScore": None
        if event.plate_text_score is None
        else _score(event.plate_text_score),
    }


def serialise_zone_event(event: ZoneEntryEvent) -> dict[str, Any]:
    return {
        "zoneId": event.zone_id,
        "globalId": event.global_id,
        "label": event.label,
        "timestampMs": _pixel(event.timestamp_ms),
        "frameIndex": event.frame_index,
    }


def serialise_vehicle(record: VehicleRecord) -> dict[str, Any]:
    return {
        "globalId": record.global_id,
        "label": record.label,
        "firstSeenMs": _pixel(record.first_seen_ms),
        "lastSeenMs": _pixel(record.last_seen_ms),
        "crossedLines": [
            {
                "lineId": crossing.line_id,
                "direction": crossing.direction,
                "timestampMs": _pixel(crossing.timestamp_ms),
            }
            for crossing in record.crossed_lines
        ],
        "zonesVisited": list(record.zones_visited),
        "reidCount": record.reid_count,
        "avgSpeedPxS": _optional_pixel(record.avg_speed_px_s),
        "avgSpeedKmh": None if record.avg_speed_kmh is None else round(record.avg_speed_kmh, 1),
        "bestPlateScore": None
        if record.best_plate_score is None
        else _score(record.best_plate_score),
        # Le texte du **vote** sur toute la vie du véhicule. `null` avec un
        # `bestPlateScore` non nul dit quelque chose de précis : une plaque a été vue,
        # aucune lecture ne fait consensus.
        "plateText": record.plate_text,
        "plateTextScore": None
        if record.plate_text_score is None
        else _score(record.plate_text_score),
        # **Pourquoi** aucune plaque n'est publiée. `null` quand il y en a une.
        # Sans ce champ, une case vide se lit comme une panne du service — et
        # l'étranglement du détecteur comme le plancher de lecture rendent le
        # silence plus fréquent, pas moins.
        "plateUnreadReason": record.plate_unread_reason,
        # Le chiffre qui rend la raison actionnable : « vue à 48 px » dit de
        # resserrer le plan, « non détectée » dit tout autre chose.
        "plateBestWidthPx": _optional_pixel(record.plate_best_width_px),
        # Le candidat sans consensus : un indice, jamais un vote. `null` dans tous
        # les cas sauf `plateUnreadReason == "no_consensus"`.
        "plateBestGuess": record.plate_best_guess,
        "plateBestGuessScore": None
        if record.plate_best_guess_score is None
        else _score(record.plate_best_guess_score),
    }


def serialise_video(info: VideoInfo) -> dict[str, Any]:
    return {
        "width": info.width,
        "height": info.height,
        "fps": round(info.fps, 3),
        "frameCount": info.frame_count,
        "durationMs": _pixel(info.duration_ms),
    }


def serialise_stats(stats: AnalysisStats) -> dict[str, Any]:
    """Le bloc que les cartes du frontend affichent, dans leur forme exacte.

    L'adaptateur absorbe la différence de vocabulaire, jamais la vue : un
    composant qui doit renommer un champ pour l'afficher est un composant qui
    connaît le serveur.
    """
    return {
        "uniqueVehicles": stats.unique_vehicles,
        "uniqueByClass": dict(stats.unique_by_class),
        "crossings": stats.crossings,
        # Des **véhicules**, pas des passages : borné par `uniqueVehicles`. C'est le
        # numérateur du taux de franchissement, qui divisait des passages par des
        # véhicules depuis ADR 0014 et pouvait donc dépasser 100 %.
        "crossedUnique": stats.crossed_unique,
        "byClass": dict(stats.by_class),
        # Véhicules et personnes séparés. Somme garantie égale à `crossings` :
        # la ventilation est dérivée du même `by_class`, jamais comptée à part.
        "byCategory": dict(stats.by_category),
        "byLine": {
            line_id: {
                "total": tally.total,
                "byClass": dict(tally.by_class),
                "byDirection": {"positive": tally.positive, "negative": tally.negative},
            }
            for line_id, tally in stats.by_line.items()
        },
        "byZone": {
            zone_id: {
                "entries": tally.entries,
                "inside": tally.inside,
                "byClass": dict(tally.by_class),
            }
            for zone_id, tally in stats.by_zone.items()
        },
        "reidHits": stats.reid_hits,
        "vehiclesPerMinute": round(stats.vehicles_per_minute, 2),
        "activeTracks": stats.active_tracks,
        "elapsedMs": _pixel(stats.elapsed_ms),
        "analysedSceneMs": _pixel(stats.analysed_scene_ms),
        "diagnostics": {
            "highDetections": stats.diagnostics.high_detections,
            "lowDetections": stats.diagnostics.low_detections,
            "maskedOut": stats.diagnostics.masked_out,
            "containedOut": stats.diagnostics.contained_out,
            "confirmedTracks": stats.diagnostics.confirmed_tracks,
            "tentativeTracks": stats.diagnostics.tentative_tracks,
            "rescuedByLowScore": stats.diagnostics.rescued_by_low_score,
        },
    }


def serialise_result(result: AnalysisResultData) -> dict[str, Any]:
    """Le résultat complet, prêt à être écrit en `json.gz`."""
    if result.stats is None:
        message = "Un résultat sans statistiques ne peut pas être sérialisé."
        raise ValueError(message)

    return {
        "jobId": result.job_id,
        "modelId": result.model_id,
        "processingFps": round(result.processing_fps, 2),
        "video": serialise_video(result.video),
        "timeline": [serialise_timeline_row(row) for row in result.timeline],
        "crossings": [serialise_crossing(event) for event in result.crossings],
        "zoneEvents": [serialise_zone_event(event) for event in result.zone_events],
        "vehicles": [serialise_vehicle(record) for record in result.vehicles],
        "stats": serialise_stats(result.stats),
    }
