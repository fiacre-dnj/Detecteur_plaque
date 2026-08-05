"""L'image de référence : reproductibilité de l'échantillon, refus explicites.

Le hash de l'échantillon est ce qui rend deux runs comparables. Il doit donc être
**stable** — pas seulement dans une exécution, mais d'une machine et d'un mois à
l'autre. C'est pour cela que l'échantillon est synthétisé par une formule qui ne
dépend que des indices, et non par un générateur pseudo-aléatoire même graine :
celui-ci dépend de la version de numpy, et le hash changerait un jour sans que
personne comprenne pourquoi deux runs ne sont plus comparables.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from traffic_analysis.core.errors import ConflictError, NotFoundError
from traffic_analysis.features.benchmark.infrastructure.reference_image import (
    SAMPLE_HEIGHT,
    SAMPLE_WIDTH,
    VideoFrameProvider,
)

if TYPE_CHECKING:
    from pathlib import Path


class TestEchantillonEmbarque:
    def test_l_echantillon_a_la_resolution_d_une_camera_de_trafic(self, tmp_path: Path) -> None:
        """Pas 640×640.

        Mesurer sur une petite entrée flatterait tous les modèles d'un facteur
        trois par rapport à l'usage réel, et le tableau servirait à choisir un
        modèle pour une charge qui n'existe pas.
        """
        image = VideoFrameProvider(tmp_path).sample()

        assert (image.width, image.height) == (SAMPLE_WIDTH, SAMPLE_HEIGHT)
        assert image.pixels.shape == (SAMPLE_HEIGHT, SAMPLE_WIDTH, 3)
        assert str(image.pixels.dtype) == "uint8"

    def test_le_hash_de_l_echantillon_est_reproductible(self, tmp_path: Path) -> None:
        """Deux appels rendent le **même** hash.

        C'est la propriété qui permet d'affirmer que deux runs pris sur
        l'échantillon sont comparables, et de le prouver au lieu de l'espérer.
        """
        provider = VideoFrameProvider(tmp_path)

        first = provider.sample()
        second = provider.sample()

        assert first.sha256 == second.sha256
        assert len(first.sha256) == 64

    def test_l_echantillon_n_est_pas_uniforme(self, tmp_path: Path) -> None:
        """Une image plate ne ferait pas travailler le post-traitement.

        Ce test ne prétend **pas** que l'échantillon contient des véhicules : il
        n'en contient pas, et `detections` y vaut 0 sur un vrai modèle (limite
        assumée, documentée dans le module et dans le schéma d'entrée). Ce qu'il
        garantit est plus modeste et suffisant : l'entrée a des contours, donc la
        mesure porte sur un travail réaliste et non sur un cas dégénéré.
        """
        pixels = VideoFrameProvider(tmp_path).sample().pixels

        assert int(pixels.min()) != int(pixels.max())
        # Assez de valeurs distinctes pour qu'il y ait des contours à traiter.
        assert len(set(pixels.reshape(-1, 3)[:, 0].tolist())) > 5


class TestFrameDeJob:
    def test_un_job_sans_repertoire_leve_un_refus_qui_dit_lequel(self, tmp_path: Path) -> None:
        provider = VideoFrameProvider(tmp_path)

        with pytest.raises(NotFoundError, match="job-inexistant"):
            provider.from_job("job-inexistant")

    def test_une_video_purgee_leve_un_refus_qui_dit_quoi_faire(self, tmp_path: Path) -> None:
        """La vidéo a un TTL plus court que le job : son absence est le cas normal.

        Le message doit donc proposer une suite — l'échantillon embarqué — au lieu
        de constater l'échec. Et surtout : **pas de repli silencieux**, qui ferait
        croire à l'utilisateur qu'il mesure sur sa propre scène.
        """
        (tmp_path / "jobs" / "job-1").mkdir(parents=True)
        provider = VideoFrameProvider(tmp_path)

        with pytest.raises(ConflictError) as caught:
            provider.from_job("job-1")

        assert caught.value.code == "benchmark_input_purged"
        assert "échantillon embarqué" in caught.value.detail

    def test_un_fichier_qui_n_est_pas_une_video_est_refuse(self, tmp_path: Path) -> None:
        directory = tmp_path / "jobs" / "job-1"
        directory.mkdir(parents=True)
        (directory / "input.mp4").write_bytes(b"ceci n'est pas une video")
        provider = VideoFrameProvider(tmp_path)

        with pytest.raises(ConflictError) as caught:
            provider.from_job("job-1")

        assert caught.value.code == "benchmark_video_unreadable"
