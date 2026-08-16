"""Audite le comptage d'un job : que montre la trajectoire, qu'a compté le serveur ?

    uv run python scripts/audit_lignes.py                    # le dernier job terminé
    uv run python scripts/audit_lignes.py <job_id>
    uv run python scripts/audit_lignes.py <job_id> --json out/audit.json

**Pourquoi ce script existe.** « Le comptage ne compte pas ce véhicule » est
irréfutable et invérifiable à la fois : l'utilisateur voit une voiture passer sur
un trait, le serveur affiche un total, et rien ne relie les deux. Ce script rejoue
la **géométrie seule** sur la timeline persistée — sans le compteur — puis compare
avec les franchissements réellement enregistrés. Il répond donc à trois questions
qu'aucun écran ne pose :

- un franchissement présent dans la trajectoire a-t-il été **refusé** ? (Si oui,
  c'est un bug du compteur, et l'audit le nomme.)
- un véhicule s'est-il **éteint à portée** d'une ligne sans la franchir ? (Alors le
  trait est mal posé, ou le suivi lâche à cet endroit.)
- la boîte a-t-elle **recouvert** la ligne sans que le centroïde change de côté ?
  (C'est l'écart entre ce que l'œil juge et ce que le compteur mesure.)

Même raison d'être que `anpr_bench.py` : un chiffre qu'on ne sait pas rejouer ne
sert qu'une fois. La géométrie est **réimplémentée localement**, délibérément — un
audit qui importerait `line_counter` ne pourrait pas contredire le compteur, donc
ne prouverait rien.
"""

from __future__ import annotations

import argparse
import gzip
import json
import math
import sqlite3
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from traffic_analysis.core.settings import get_settings

if TYPE_CHECKING:
    from collections.abc import Sequence

type XY = tuple[float, float]

#: Une piste éteinte à moins d'une demi-boîte d'une ligne s'est manquée de peu.
#: Le même seuil que `line_counter.NEAR_MISS_RATIO`, et la même raison de le tenir
#: relatif à la boîte plutôt qu'en pixels : il doit vouloir dire la même chose en
#: 720p et en 4K.
NEAR_MISS_RATIO = 1.0


# ── Géométrie, réimplémentée exprès ──────────────────────────────────────────


def _orient(a: XY, b: XY, c: XY) -> int:
    value = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
    if abs(value) < 1e-9:
        return 0
    return 1 if value > 0 else -1


def _segments_intersect(p1: XY, p2: XY, a: XY, b: XY) -> bool:
    d1, d2 = _orient(p1, p2, a), _orient(p1, p2, b)
    d3, d4 = _orient(a, b, p1), _orient(a, b, p2)
    if d1 != d2 and d3 != d4:
        return not (d1 == d2 == 0 or d3 == d4 == 0)
    return False


def _point_segment_distance(p: XY, a: XY, b: XY) -> float:
    dx, dy = b[0] - a[0], b[1] - a[1]
    length_squared = dx * dx + dy * dy
    if length_squared <= 0.0:
        return math.hypot(p[0] - a[0], p[1] - a[1])
    t = max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / length_squared))
    return math.hypot(p[0] - (a[0] + t * dx), p[1] - (a[1] + t * dy))


def _box_touches(box: dict[str, float], a: XY, b: XY) -> bool:
    """La boîte recouvre-t-elle le segment ? **Ce que l'œil de l'utilisateur juge.**"""
    x0, y0 = box["x"], box["y"]
    x1, y1 = x0 + box["width"], y0 + box["height"]
    if any(x0 <= p[0] <= x1 and y0 <= p[1] <= y1 for p in (a, b)):
        return True
    corners: list[XY] = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    return any(_segments_intersect(corners[i], corners[(i + 1) % 4], a, b) for i in range(4))


# ── Lecture des données du job ───────────────────────────────────────────────


def _load_job(job_id: str | None) -> tuple[str, dict[str, Any], list[dict[str, Any]]]:
    """Rend `(job_id, résultat, lignes)`. Sans identifiant, prend le dernier terminé."""
    settings = get_settings()
    database = settings.data_dir / "traffic.db"
    if not database.exists():
        message = f"Base introuvable : {database}"
        raise SystemExit(message)

    connection = sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    if job_id is None:
        row = connection.execute(
            "select id, config_json from jobs where status = 'done' "
            "order by created_at desc limit 1"
        ).fetchone()
    else:
        row = connection.execute(
            "select id, config_json from jobs where id = ?", (job_id,)
        ).fetchone()
    if row is None:
        message = f"Aucun job {'terminé' if job_id is None else job_id} en base."
        raise SystemExit(message)

    result_file = settings.data_dir / "jobs" / row["id"] / "result.json.gz"
    if not result_file.exists():
        message = f"Résultat absent : {result_file}"
        raise SystemExit(message)
    with gzip.open(result_file, "rt", encoding="utf-8") as handle:
        result = json.load(handle)

    lines = json.loads(row["config_json"]).get("lines", [])
    return row["id"], result, lines


def _paths(result: dict[str, Any]) -> dict[int, list[tuple[float, XY, dict[str, float]]]]:
    """Trajectoires par numéro de véhicule, dans l'ordre du temps.

    Indexées par `globalId` et non par `trackId` : c'est le numéro sous lequel on
    compte, donc la seule clé qui permette de confronter trajectoire et
    franchissements.
    """
    paths: dict[int, list[tuple[float, XY, dict[str, float]]]] = {}
    for row in result["timeline"]:
        for track in row["tracks"]:
            box = track["box"]
            centroid = (box["x"] + box["width"] / 2.0, box["y"] + box["height"] / 2.0)
            paths.setdefault(track["globalId"], []).append((row["timestampMs"], centroid, box))
    return paths


# ── L'audit ──────────────────────────────────────────────────────────────────


def audit(result: dict[str, Any], lines: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Confronte la géométrie des trajectoires aux franchissements enregistrés."""
    paths = _paths(result)
    counted: dict[tuple[int, str], int] = {
        (event["globalId"], event["lineId"]): event["direction"] for event in result["crossings"]
    }

    per_line: dict[str, dict[str, Any]] = {}
    refused: list[dict[str, Any]] = []
    near: list[dict[str, Any]] = []

    for line in lines:
        a: XY = (line["a"]["x"], line["a"]["y"])
        b: XY = (line["b"]["x"], line["b"]["y"])
        geometric = 0

        for global_id in sorted(paths):
            path = paths[global_id]
            crossings = 0
            previous_side = 0
            touched = False
            for index, (_, centroid, box) in enumerate(path):
                touched = touched or _box_touches(box, a, b)
                current = _orient(a, b, centroid)
                if current == 0:
                    continue
                if previous_side == 0:
                    previous_side = current
                    continue
                if current != previous_side:
                    if _segments_intersect(path[index - 1][1], centroid, a, b):
                        crossings += 1
                    previous_side = current

            geometric += crossings
            key = (global_id, line["id"])
            if crossings and key not in counted:
                refused.append(
                    {"globalId": global_id, "lineId": line["id"], "crossings": crossings}
                )
            if crossings == 0 and key not in counted:
                _, last_centroid, last_box = path[-1]
                half_extent = max(last_box["width"], last_box["height"]) / 2.0
                distance = _point_segment_distance(last_centroid, a, b)
                ratio = distance / half_extent if half_extent > 0 else math.inf
                if ratio <= NEAR_MISS_RATIO:
                    near.append(
                        {
                            "globalId": global_id,
                            "lineId": line["id"],
                            "distancePx": round(distance, 1),
                            "halfExtentPx": round(half_extent, 1),
                            "boxTouchedLine": touched,
                            "lastSeenMs": path[-1][0],
                        }
                    )

        per_line[line["id"]] = {
            "name": line["name"],
            "geometric": geometric,
            "counted": sum(1 for (_, line_id) in counted if line_id == line["id"]),
        }

    return {
        "lines": per_line,
        "refused": refused,
        "nearMisses": near,
        "totals": {
            "tracks": len(paths),
            "geometric": sum(entry["geometric"] for entry in per_line.values()),
            "counted": len(counted),
        },
    }


def report(job_id: str, result: dict[str, Any], report_data: dict[str, Any]) -> None:
    totals = report_data["totals"]
    video = result["video"]
    print(f"job {job_id} — {video['width']}×{video['height']}, {video['durationMs'] / 1000:.1f} s")
    print(
        f"{totals['tracks']} pistes dans la timeline, "
        f"{totals['geometric']} franchissements géométriques, "
        f"{totals['counted']} comptés\n"
    )

    print(f"{'ligne':<28}{'géométrique':>12}{'compté':>9}")
    for line_id, entry in report_data["lines"].items():
        label = f"{line_id} « {entry['name']} »"
        print(f"{label:<28}{entry['geometric']:>12}{entry['counted']:>9}")

    if report_data["refused"]:
        # Le seul cas qui accuse le compteur. Il doit sauter aux yeux.
        print("\n*** FRANCHISSEMENTS REFUSÉS — bug du compteur ***")
        for entry in report_data["refused"]:
            print(f"    #{entry['globalId']} sur {entry['lineId']} ×{entry['crossings']}")
    else:
        print("\nAucun franchissement refusé : tout ce que la trajectoire montre a compté.")

    if report_data["nearMisses"]:
        print("\nQuasi-franchissements — pistes éteintes à portée d'une ligne :")
        for entry in report_data["nearMisses"]:
            touched = "boîte sur le trait" if entry["boxTouchedLine"] else "boîte à côté"
            print(
                f"    #{entry['globalId']:<4} {entry['lineId']:<6} "
                f"éteinte à {entry['distancePx']:6.1f} px du trait "
                f"(demi-boîte {entry['halfExtentPx']:.1f} px, {touched}) "
                f"à {entry['lastSeenMs'] / 1000:.1f} s"
            )
        print(
            "\n  Ces pistes n'ont franchi aucune ligne et ne comptent nulle part. Une ligne\n"
            "  qui en accumule est posée là où le suivi s'arrête — bord de l'image, ou\n"
            "  champ lointain où les véhicules deviennent trop petits pour être suivis."
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "job_id", nargs="?", help="identifiant du job ; défaut : le dernier terminé"
    )
    parser.add_argument("--json", type=Path, help="écrit le rapport complet dans ce fichier")
    args = parser.parse_args()

    job_id, result, lines = _load_job(args.job_id)
    if not lines:
        print(f"job {job_id} : aucune ligne de comptage dans la configuration.")
        return 0

    report_data = audit(result, lines)
    report(job_id, result, report_data)

    if args.json is not None:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(
            json.dumps({"jobId": job_id, **report_data}, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        print(f"\nrapport écrit : {args.json}")

    # Un franchissement refusé est une anomalie du compteur : le dire par le code
    # de sortie, pour que le script soit utilisable dans une vérification.
    return 1 if report_data["refused"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
