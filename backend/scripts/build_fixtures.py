"""Régénère les fixtures JSON que le frontend parse dans un type explicite.

    uv run python scripts/build_fixtures.py

**Pourquoi ce script existe.** `frontend/src/shared/api/__fixtures__/*.json` sont
le seul garde-fou automatique entre les deux moitiés du projet : elles sont
produites par les **vrais sérialiseurs**, committées, et parsées côté frontend
dans un type explicite. Un champ renommé côté Python casse donc un test côté
TypeScript, sans monorepo tool.

Ce mécanisme ne tient que si les fixtures sont **régénérées** et non corrigées à
la main. Une fixture éditée à la main pour faire passer `tsc` retire précisément la
propriété qu'on cherchait : elle affirme alors ce que le frontend espère, au lieu
de ce que le backend produit. Jusqu'ici la régénération se faisait de mémoire —
d'où ce script.

La scène est volontairement petite et **entièrement déterministe** : trois
véhicules, deux franchissements, une plaque lue, une plaque vue mais non lue, et
une plaque lue plusieurs fois sans qu'aucune lecture ne fasse majorité. C'est le
jeu minimal qui exerce les quatre états de plaque que l'interface doit
distinguer.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests.support.builders import (
    CAR,
    TRUCK,
    compose,
    make_line,
    straight_line,
    track_path,
)
from tests.support.engine import (
    FakeEngine,
    FakePlateDetector,
    FakePlateReader,
)

from traffic_analysis.features.counting.application.analysis_service import (
    AnalysisService,
)
from traffic_analysis.features.counting.application.dto import (
    AnalysisJobConfig,
    PlateOcrOptions,
)
from traffic_analysis.features.counting.application.serializers import (
    serialise_result,
)

if TYPE_CHECKING:
    from traffic_analysis.features.counting.domain.models import BoundingBox

FIXTURES = (
    Path(__file__).resolve().parents[2] / "frontend" / "src" / "shared" / "api" / "__fixtures__"
)

#: Assez large pour dépasser `min_vehicle_width_px` : sous ce seuil, la détection
#: de plaques est écartée et la fixture ne porterait aucun rectangle.
VEHICLE_SIZE = (160.0, 120.0)


#: Abscisse du véhicule 3 : constante sur toute sa trajectoire (seul `y` varie),
#: ce qui permet de reconnaître ses lectures par position dans `_text_for`.
DISCORDANT_VEHICLE_X = 2100.0


def _readable(box: BoundingBox) -> bool:
    """Lisible pour les véhicules 1 et 3, illisible pour le véhicule 2.

    C'est ce qui donne à la fixture ses **quatre** états de plaque : lue, vue mais
    illisible, lue sans consensus, absente. Le véhicule 2 (illisible) est celui que
    l'interface rate le plus facilement, et n'existerait pas si tout était lisible.
    """
    return box.x < 1000.0 or box.x > 1900.0


def _text_for(box: BoundingBox, *, discordant_reads: list[int]) -> str:
    """Le véhicule 1 lit toujours la même plaque ; le véhicule 3 jamais deux fois
    la même graphie de suite, pour que son vote n'atteigne jamais le consensus —
    le seul moyen d'exercer `plateBestGuess`, qui n'a de sens que sous
    `no_consensus`. Deux longueurs distinctes : à longueur égale, le consensus par
    caractère pourrait trancher là où le vote par chaîne entière refuse.

    `box` est celle de la **plaque**, décalée du centre du véhicule qui l'a
    produite (voir `FakePlateDetector.detect_many`) — une comparaison exacte à
    `DISCORDANT_VEHICLE_X` ne matcherait donc jamais. Une plage large suffit,
    puisque les trois véhicules de la scène sont à plus de 400 px les uns des
    autres.
    """
    if abs(box.x - DISCORDANT_VEHICLE_X) > 200.0:
        return "ab-123-cd"
    index = discordant_reads[0]
    discordant_reads[0] += 1
    return ("ab-123-cd", "xy-78-zw")[index % 2]


def build_result() -> dict[str, Any]:
    frames = compose(
        track_path(
            1, CAR, straight_line((700.0, 250.0), (700.0, 800.0), steps=12), box_size=VEHICLE_SIZE
        ),
        track_path(
            2,
            TRUCK,
            straight_line((1200.0, 800.0), (1200.0, 250.0), steps=12),
            box_size=VEHICLE_SIZE,
        ),
        track_path(
            3,
            CAR,
            straight_line((DISCORDANT_VEHICLE_X, 250.0), (DISCORDANT_VEHICLE_X, 800.0), steps=12),
            box_size=VEHICLE_SIZE,
        ),
    )
    discordant_reads = [0]
    service = AnalysisService(
        FakeEngine(frames),
        FakePlateDetector(),
        FakePlateReader(
            is_readable=_readable,
            text_for=lambda box: _text_for(box, discordant_reads=discordant_reads),
        ),
        PlateOcrOptions(min_width_px=8.0),
    )
    result = service.run_video(
        "fixture-job",
        Path("/inexistant.mp4"),
        AnalysisJobConfig(
            model_id="yolov8n",
            lines=(make_line(),),
            detect_plates=True,
            read_plate_text=True,
        ),
    )
    # La cadence dépend de la machine : elle est figée pour que deux régénérations
    # sur deux machines ne produisent pas un diff illisible.
    result.processing_fps = 262.24
    return serialise_result(result)


def build_preview(result: dict[str, Any]) -> dict[str, Any]:
    """Un aperçu, **par les mêmes sérialiseurs** que le temps réel.

    C'est ce qui permet au navigateur de dessiner les deux modes avec un seul
    chemin de rendu, donc de ne pas avoir deux overlays qui divergent.
    """
    row = result["timeline"][len(result["timeline"]) // 2]
    return {
        "jobId": "job-demo",
        "frameIndex": row["frameIndex"],
        "timestampMs": row["timestampMs"],
        "frameWidth": result["video"]["width"],
        "frameHeight": result["video"]["height"],
        "tracks": row["tracks"],
        "crossings": result["crossings"][:1],
        "zoneEvents": [],
        "stats": result["stats"],
    }


def main() -> int:
    result = build_result()
    preview = build_preview(result)

    for name, payload in (("analysis-result.json", result), ("job-preview.json", preview)):
        path = FIXTURES / name
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"  écrit : {path}")

    print(
        "\n  Relancez `bun run typecheck` : un champ ajouté au contrat doit casser\n"
        "  **une fois**, puis passer. S'il ne casse pas, la fixture n'exerce pas ce\n"
        "  champ et le garde-fou ne protège rien."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
