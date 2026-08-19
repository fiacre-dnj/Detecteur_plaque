"""Le décodage, désormais dans un fil : ce qui doit rester vrai image pour image.

Ce chemin est neuf et il porte tout le temps de scène. Il n'a besoin ni de poids ni
de GPU — seulement d'OpenCV et d'un fichier — donc la CI peut le traverser
entièrement, contrairement à `model.track()`. C'est une chance rare dans ce module,
et ces tests en profitent pour verrouiller les quatre propriétés dont le reste de
l'application dépend :

1. **l'index rendu est l'index dans le fichier**, donc `timestamp_ms` est juste
   (invariant 1). Un décalage d'un cran ne lève rien : il date les franchissements à
   côté, et personne ne le voit jamais ;
2. **le déplacement est vérifié, pas supposé.** `CAP_PROP_POS_FRAMES` est
   approximatif sur plusieurs conteneurs ; l'accepter tel quel donnerait des
   horodatages faux sans aucune exception ;
3. **le fil meurt avec le générateur.** Un consommateur qui s'arrête au milieu — une
   fenêtre d'analyse qui atteint sa borne, une annulation — ne doit pas laisser un
   fil vivant sur un décodeur ouvert ;
4. **une exception du décodage traverse le fil.** Sinon un flux vide se lirait comme
   une analyse réussie sans le moindre véhicule.
"""

from __future__ import annotations

import threading
from time import perf_counter
from typing import TYPE_CHECKING

import numpy as np
import pytest

from traffic_analysis.core.errors import UnsupportedMediaError
from traffic_analysis.features.models_registry.infrastructure.ultralytics_engine import (
    _batched,
    _iter_decoded,
    decode_ahead,
)

if TYPE_CHECKING:
    from pathlib import Path

    import numpy.typing as npt

#: Un fil de décodage doit avoir disparu bien avant cette échéance.
#:
#: Une **échéance en temps** et non un nombre de tours de boucle : un test dont le
#: verdict dépend de la vitesse de la machine ne prouve rien (`CLAUDE.md`, Tests).
JOIN_DEADLINE_S = 3.0


def _write_video(path: Path, *, frames: int, width: int = 96, height: int = 64) -> None:
    """Une vidéo dont **chaque image est reconnaissable**.

    Le motif encode l'index dans une bande verticale dont la position avance d'une
    image à l'autre : c'est ce qui permet de comparer « l'image que le décodeur dit
    être la cinquième » avec « la cinquième image du fichier », donc de repérer un
    décalage d'un cran. Des images identiques rendraient tous ces tests aveugles au
    seul bug qu'ils cherchent.
    """
    import cv2

    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 25.0, (width, height))
    assert writer.isOpened(), "OpenCV n'a pas d'encodeur mp4v : ce test ne peut rien vérifier."
    try:
        for index in range(frames):
            frame = np.zeros((height, width, 3), dtype=np.uint8)
            frame[:, (index * 3) % width : ((index * 3) % width) + 6] = 255
            writer.write(frame)
    finally:
        writer.release()


def _read_all(path: Path) -> list[npt.NDArray[np.uint8]]:
    """Toutes les images, lues de la façon la plus bête possible.

    La référence des tests d'équivalence : une boucle `read()` sans déplacement, sans
    pas et sans fil. Si le décodeur du moteur en diverge, c'est lui qui a tort.
    """
    import cv2

    capture = cv2.VideoCapture(str(path))
    frames: list[npt.NDArray[np.uint8]] = []
    try:
        while True:
            ok, frame = capture.read()
            if not ok:
                return frames
            frames.append(frame)
    finally:
        capture.release()


def _decode_threads() -> list[threading.Thread]:
    return [thread for thread in threading.enumerate() if thread.name == "traffic-decode"]


class TestIndexEtDeplacement:
    def test_sans_pas_ni_borne_les_images_sont_celles_du_fichier(self, tmp_path: Path) -> None:
        """L'équivalence de base : mêmes images, mêmes index, dans l'ordre."""
        video = tmp_path / "clip.mp4"
        _write_video(video, frames=12)
        expected = _read_all(video)

        decoded = list(_iter_decoded(video, stride=1, first_index=0))

        assert [index for index, _ in decoded] == list(range(len(expected)))
        for (_, actual), reference in zip(decoded, expected, strict=True):
            assert np.array_equal(actual, reference)

    @pytest.mark.parametrize("stride", [2, 3, 5])
    def test_le_pas_saute_des_images_sans_decaler_les_index(
        self, tmp_path: Path, stride: int
    ) -> None:
        """`frame_index` reste l'index **dans le fichier**, pas le rang de l'image
        analysée.

        C'est la propriété qui fait que `timestamp_ms = index / fps` reste du temps de
        scène avec un pas d'analyse. Rendre 0, 1, 2 au lieu de 0, 3, 6 diviserait
        tous les horodatages par le pas — donc les vitesses, et la place de chaque
        franchissement sur la barre de lecture.
        """
        video = tmp_path / "clip.mp4"
        _write_video(video, frames=13)
        expected = _read_all(video)

        decoded = list(_iter_decoded(video, stride=stride, first_index=0))

        assert [index for index, _ in decoded] == list(range(0, len(expected), stride))
        for index, actual in decoded:
            assert np.array_equal(actual, expected[index])

    @pytest.mark.parametrize("first_index", [1, 4, 7])
    def test_le_deplacement_tombe_sur_l_image_demandee(
        self, tmp_path: Path, first_index: int
    ) -> None:
        """**Le mode de panne que rien ne signale.** Un déplacement approximatif
        accepté sans vérification rendrait l'image d'à côté sous le bon index : le
        comptage resterait plausible et tous ses horodatages seraient faux.

        La comparaison porte sur les **pixels**, seule preuve possible : l'index, lui,
        est produit par le code testé.
        """
        video = tmp_path / "clip.mp4"
        _write_video(video, frames=12)
        expected = _read_all(video)

        decoded = list(_iter_decoded(video, stride=1, first_index=first_index))

        assert decoded[0][0] == first_index
        assert np.array_equal(decoded[0][1], expected[first_index])
        assert len(decoded) == len(expected) - first_index

    def test_une_borne_au_dela_de_la_fin_rend_un_flux_vide(self, tmp_path: Path) -> None:
        """Et non une exception : c'est `AnalysisService` qui décide du message, lui
        seul connaît la durée **et** les deux bornes de la fenêtre demandée."""
        video = tmp_path / "clip.mp4"
        _write_video(video, frames=6)

        assert list(_iter_decoded(video, stride=1, first_index=99)) == []

    def test_un_fichier_illisible_leve_le_message_du_domaine(self, tmp_path: Path) -> None:
        """Une vidéo qu'OpenCV ne peut pas ouvrir n'est pas une vidéo, quoi qu'en dise
        son extension."""
        fake = tmp_path / "pas-une-video.mp4"
        fake.write_bytes(b"ceci n'est pas un conteneur")

        with pytest.raises(UnsupportedMediaError):
            list(_iter_decoded(fake, stride=1, first_index=0))


class TestLots:
    def test_le_dernier_lot_peut_etre_plus_court(self) -> None:
        """Une vidéo dont le nombre d'images n'est pas un multiple du lot est le cas
        courant, pas un cas limite : perdre le reste perdrait la fin de l'analyse."""
        frames = [(index, np.zeros((1, 1, 3), dtype=np.uint8)) for index in range(7)]

        chunks = list(_batched(iter(frames), 3))

        assert [[index for index, _ in chunk] for chunk in chunks] == [[0, 1, 2], [3, 4, 5], [6]]

    def test_un_lot_nul_ne_boucle_pas_a_l_infini(self) -> None:
        """`batch=0` est refusé par les réglages, mais un lot vide rendrait ici un
        générateur qui n'avance jamais — une analyse figée sans message."""
        frames = [(index, np.zeros((1, 1, 3), dtype=np.uint8)) for index in range(3)]

        chunks = list(_batched(iter(frames), 0))

        assert [len(chunk) for chunk in chunks] == [1, 1, 1]


class TestFilDeDecodage:
    def test_le_fil_rend_exactement_ce_que_le_decodage_rend(self, tmp_path: Path) -> None:
        """Le fil est un **recouvrement**, pas une transformation : ni image perdue,
        ni image réordonnée, ni index changé."""
        video = tmp_path / "clip.mp4"
        _write_video(video, frames=11)
        expected = list(_iter_decoded(video, stride=1, first_index=0))

        batches = list(
            decode_ahead(video, stride=1, first_index=0, batch=4, frame_bytes=96 * 64 * 3)
        )

        flattened = [frame for chunk in batches for frame in chunk]
        assert [index for index, _ in flattened] == [index for index, _ in expected]
        for (_, actual), (_, reference) in zip(flattened, expected, strict=True):
            assert np.array_equal(actual, reference)
        assert [len(chunk) for chunk in batches] == [4, 4, 3]

    def test_s_arreter_au_milieu_ne_laisse_pas_de_fil_vivant(self, tmp_path: Path) -> None:
        """**La fuite que ce test existe pour interdire.**

        `AnalysisService` sort de sa boucle sur la borne de fin d'une fenêtre et sur
        une annulation. Le budget est réglé ici pour que la file soit pleine et le
        producteur bloqué au moment où l'on abandonne : c'est exactement la situation
        où un `put` sans expiration ne rendrait jamais la main, et où le fil
        survivrait au job avec son décodeur ouvert.
        """
        video = tmp_path / "clip.mp4"
        _write_video(video, frames=40)
        before = _decode_threads()

        batches = decode_ahead(
            video,
            stride=1,
            first_index=0,
            batch=2,
            frame_bytes=96 * 64 * 3,
            # Un seul lot en vol : le producteur bloque dès le deuxième.
            budget_bytes=96 * 64 * 3 * 2,
        )
        next(iter(batches))
        batches.close()

        deadline = perf_counter() + JOIN_DEADLINE_S
        while perf_counter() < deadline and len(_decode_threads()) > len(before):
            pass
        assert len(_decode_threads()) == len(before)

    def test_une_erreur_de_decodage_est_relevee_chez_l_appelant(self, tmp_path: Path) -> None:
        """Levée **dans le fil appelant**, à l'endroit où il l'attend.

        Une exception avalée par le fil rendrait un flux vide, c'est-à-dire une
        analyse « terminée » sans un seul véhicule — et l'utilisateur chercherait le
        défaut dans sa vidéo.
        """
        fake = tmp_path / "pas-une-video.mp4"
        fake.write_bytes(b"ceci n'est pas un conteneur")

        with pytest.raises(UnsupportedMediaError):
            list(decode_ahead(fake, stride=1, first_index=0, batch=2, frame_bytes=1024))
