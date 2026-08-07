"""Ce que le banc de mesure garantit, sans modèle ni vidéo.

Un banc dont on ne vérifie rien mesure ce qu'il veut. Ces tests portent sur les
deux propriétés dont dépend la validité de **toutes** les mesures qu'il produit :

1. **le rendu synthétique est déterministe** — sinon deux exécutions du même
   palier donnent deux scores, et le `--compare` compare du bruit ;
2. **les agrégats disent ce qu'ils prétendent** — un p95 faux ferait conclure à un
   gain là où il n'y en a pas.

La lecture elle-même n'est pas testée ici : elle demande le modèle d'OCR, que la
CI n'a pas. C'est le rôle de `--truth-ladder`, lancé à la main sur une machine
équipée, et dont le tableau part dans l'ADR.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "anpr_bench",
    Path(__file__).resolve().parents[2] / "scripts" / "anpr_bench.py",
)
assert _SPEC is not None
assert _SPEC.loader is not None
anpr_bench = importlib.util.module_from_spec(_SPEC)
sys.modules["anpr_bench"] = anpr_bench
_SPEC.loader.exec_module(anpr_bench)


class TestRenduSynthetique:
    def test_le_rendu_est_deterministe_pour_une_meme_graine(self) -> None:
        """**La propriété dont dépend tout le reste.**

        Le bruit vient d'un générateur explicitement grainé, jamais de `np.random`
        global. Sans cela, relancer l'échelle donnerait un tableau légèrement
        différent à chaque fois, et on attribuerait la variation au réglage qu'on
        venait de changer.
        """
        params = anpr_bench.RenderParams()

        first = anpr_bench.render_plate("AB-123-CD", 128, params, seed=3)
        second = anpr_bench.render_plate("AB-123-CD", 128, params, seed=3)

        assert (first == second).all()

    def test_deux_graines_differentes_rendent_deux_images(self) -> None:
        """Sinon les huit plaques d'un palier partageraient le même bruit, et le
        palier mesurerait une seule condition répétée huit fois."""
        params = anpr_bench.RenderParams()

        first = anpr_bench.render_plate("AB-123-CD", 128, params, seed=1)
        second = anpr_bench.render_plate("AB-123-CD", 128, params, seed=2)

        assert not (first == second).all()

    @pytest.mark.parametrize("width", [320, 128, 64, 48])
    def test_la_largeur_demandee_est_respectee_et_le_rapport_tenu(self, width: int) -> None:
        """Le palier **est** la largeur : la rater invaliderait l'axe des mesures."""
        plate = anpr_bench.render_plate("AB-123-CD", width, anpr_bench.RenderParams(), seed=0)

        height, rendered_width = plate.shape[:2]
        assert rendered_width == width
        # 4,6:1, le rapport d'une plaque française, à un pixel d'arrondi près.
        assert abs(rendered_width / height - 4.6) < 0.35

    def test_les_parametres_de_rendu_partent_dans_le_json(self) -> None:
        """Sans eux, deux rapports ne sont pas comparables et `--compare` compare
        deux inconnues. Même discipline que l'`imageHash` de `BenchmarkRun`."""
        rendered = anpr_bench.RenderParams().as_json()

        assert set(rendered) == {
            "sourceWidth",
            "blurRatio",
            "noiseSigma",
            "jpegQuality",
            "skewDegrees",
        }


class TestAgregats:
    def test_les_percentiles_ne_mentent_pas_sur_la_queue(self) -> None:
        """Une moyenne cacherait la queue, et c'est la queue qui gêne."""
        values = [10.0] * 95 + [100.0] * 5

        stats = anpr_bench._percentiles(values)

        assert stats["p50"] == 10.0
        assert stats["p95"] == 100.0
        assert stats["count"] == 100

    def test_des_mesures_absentes_rendent_zero_plutot_que_de_lever(self) -> None:
        """Un banc qui plante sur une vidéo sans détection ne rend aucun rapport."""
        assert anpr_bench._percentiles([]) == {"p50": 0.0, "p95": 0.0, "count": 0}

    def test_l_histogramme_range_chaque_valeur_dans_un_seul_seau(self) -> None:
        edges = (0.05, 0.1, 0.25, 0.5, 0.9)
        values = [0.02, 0.07, 0.15, 0.3, 0.6, 0.99]

        histogram = anpr_bench._histogram(values, edges)

        assert sum(histogram.values()) == len(values)
        # La séparation d'ADR 0008 : une plaque à 15 % de la largeur du véhicule,
        # une fausse détection à 99 %. Les deux doivent tomber dans deux seaux.
        assert histogram["0.1-0.25"] == 1
        assert histogram[">=0.9"] == 1

    def test_un_histogramme_vide_ne_leve_pas(self) -> None:
        assert anpr_bench._histogram([], (1.0, 2.0)) == {}


class TestEchelleDeVerite:
    def test_les_paliers_descendent_de_320_a_48(self) -> None:
        """Ce sont ceux d'ADR 0007. Le banc doit reproduire son tableau avant qu'on
        lui fasse confiance pour mesurer autre chose."""
        assert anpr_bench.TRUTH_LADDER_WIDTHS[0] == 320
        assert anpr_bench.TRUTH_LADDER_WIDTHS[-1] == 48
        assert list(anpr_bench.TRUTH_LADDER_WIDTHS) == sorted(
            anpr_bench.TRUTH_LADDER_WIDTHS, reverse=True
        )
        # 64 px est le dernier palier où la mesure donne encore des lectures
        # justes : c'est lui qui justifie `min_width_px = 64` plutôt que 150.
        assert 64 in anpr_bench.TRUTH_LADDER_WIDTHS

    def test_huit_plaques_de_verite_terrain(self) -> None:
        """Huit et non trois : moins ne rendrait que 0, 1/3 ou 1 par palier, et la
        décroissance ne se lirait pas."""
        assert len(anpr_bench.TRUTH_PLATES) == 8
        assert len(set(anpr_bench.TRUTH_PLATES)) == 8
