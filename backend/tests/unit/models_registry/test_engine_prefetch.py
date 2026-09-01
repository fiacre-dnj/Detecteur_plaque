"""Le recouvrement du moteur par l'aval : ce qui doit rester vrai.

`prefetch` fait avancer le suivi d'un lot pendant que `AnalysisService` travaille
sur le précédent — plaques, OCR, captures, apparence. C'est un changement de
**calendrier**, jamais de résultat, et c'est précisément ce qui le rend livrable :
un fil qui réordonnerait, perdrait ou dupliquerait une image produirait des
horodatages plausibles et faux (invariant 1), c'est-à-dire la panne que ce module
a déjà payée deux fois.

Ces tests n'ont besoin ni de poids, ni de GPU, ni d'OpenCV : `prefetch` est
générique, donc la CI le traverse entièrement.

Quatre propriétés, chacune adossée à un mode de panne :

1. **la suite rendue est celle de la source**, à l'identique et dans l'ordre ;
2. **le producteur prend de l'avance**, sinon le recouvrement n'existe pas et le
   réglage ne serait qu'un fil de plus au repos ;
3. **s'arrêter au milieu ne laisse pas de fil vivant** — une annulation, une borne
   de fenêtre. Ici la conséquence est pire qu'une fuite : le fil tient le modèle,
   et `iter_video` rendrait son bail sous une inférence en vol (invariant 9) ;
4. **une exception traverse**, sinon un flux vide se lirait comme une analyse
   réussie et sans le moindre véhicule.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from time import perf_counter

import pytest

from traffic_analysis.features.models_registry.infrastructure.ultralytics_engine import prefetch

#: Un fil de préchargement doit avoir disparu bien avant cette échéance.
#:
#: Une **échéance en temps** et non un nombre de tours de boucle : un test dont le
#: verdict dépend de la vitesse de la machine ne prouve rien (`CLAUDE.md`, Tests).
JOIN_DEADLINE_S = 3.0

THREAD_NAME = "test-prefetch"


def _threads() -> list[threading.Thread]:
    return [thread for thread in threading.enumerate() if thread.name == THREAD_NAME]


class TestEquivalence:
    def test_rend_exactement_la_suite_de_la_source(self) -> None:
        """Ni élément perdu, ni élément réordonné, ni élément dupliqué."""
        source = iter(range(23))

        assert list(prefetch(source, depth=2, name=THREAD_NAME)) == list(range(23))

    def test_une_profondeur_nulle_rend_le_chemin_sequentiel(self) -> None:
        """`0` est le **témoin**, pas un repli de secours.

        Il doit rendre exactement l'ancien chemin — aucun fil, donc aucun ordre
        d'exécution nouveau — pour qu'une mesure « avec » se compare à une mesure
        « sans » dans le même processus.
        """
        consumed: list[int] = []

        def source() -> Iterator[int]:
            for value in range(4):
                consumed.append(value)
                yield value

        stream = prefetch(source(), depth=0, name=THREAD_NAME)
        first = next(stream)

        # Sans fil, rien n'est produit d'avance : la source s'arrête au `yield`.
        assert first == 0
        assert consumed == [0]
        assert not _threads()
        stream.close()

    def test_une_source_vide_ne_rend_rien_et_ne_bloque_pas(self) -> None:
        """Le cas d'une fenêtre d'analyse posée au-delà de la fin du fichier."""
        assert list(prefetch(iter(()), depth=1, name=THREAD_NAME)) == []


class TestRecouvrement:
    def test_le_producteur_prend_de_l_avance(self) -> None:
        """**La propriété pour laquelle ce code existe.**

        Sans elle, le fil ne recouvre rien : le suivi de l'image suivante
        n'aurait toujours lieu qu'une fois l'aval terminé, et la cadence resterait
        la somme des deux étages au lieu du plus grand.
        """
        produced: list[int] = []
        released = threading.Event()

        def source() -> Iterator[int]:
            for value in range(4):
                produced.append(value)
                yield value

        stream = prefetch(source(), depth=2, name=THREAD_NAME)
        first = next(stream)
        assert first == 0

        # Le consommateur n'a demandé qu'un élément ; le producteur, lui, doit avoir
        # rempli la file pendant ce temps. Échéance en temps, jamais en itérations.
        deadline = perf_counter() + JOIN_DEADLINE_S
        while perf_counter() < deadline and len(produced) < 3:
            released.wait(0.01)
        assert len(produced) >= 3

        stream.close()

    def test_la_file_est_bornee_par_la_profondeur(self) -> None:
        """Un lot d'avance recouvre ; une file sans fond retiendrait la vidéo entière
        en images décodées **et** en résultats de suivi."""
        produced: list[int] = []

        def source() -> Iterator[int]:
            for value in range(100):
                produced.append(value)
                yield value

        stream = prefetch(source(), depth=1, name=THREAD_NAME)
        next(stream)

        deadline = perf_counter() + 0.5
        while perf_counter() < deadline:
            pass
        # Un élément consommé, un dans la file, un bloqué dans le `put` : la marge
        # est large exprès, ce qui compte est que ce ne soit pas 100.
        assert len(produced) <= 5

        stream.close()


class TestFilDePrechargement:
    def test_s_arreter_au_milieu_ne_laisse_pas_de_fil_vivant(self) -> None:
        """**La fuite que ce test existe pour interdire**, et elle est pire qu'une fuite.

        Le fil tient le modèle. `iter_video` le fait tourner *sous* un bail : rendre
        la main pendant qu'un `track()` est en vol relâcherait le bail sous
        l'inférence, et deux jobs partageraient une instance — invariant 9,
        c'est-à-dire des chiffres plausibles et faux.
        """
        before = _threads()

        def source() -> Iterator[int]:
            yield from range(10_000)

        stream = prefetch(source(), depth=1, name=THREAD_NAME)
        next(stream)
        stream.close()

        deadline = perf_counter() + JOIN_DEADLINE_S
        while perf_counter() < deadline and len(_threads()) > len(before):
            pass
        assert len(_threads()) == len(before)

    def test_la_source_est_fermee_explicitement(self) -> None:
        """Elle tient le fil de **décodage**, un étage plus bas.

        La fermeture en cascade d'une boucle `for` passe par le ramasse-miettes :
        chaque job annulé laisserait un décodeur ouvert le temps qu'il veuille.
        """
        closed = threading.Event()

        def source() -> Iterator[int]:
            try:
                yield from range(10_000)
            finally:
                closed.set()

        stream = prefetch(source(), depth=1, name=THREAD_NAME)
        next(stream)
        stream.close()

        assert closed.wait(JOIN_DEADLINE_S)

    def test_une_exception_est_relevee_chez_l_appelant(self) -> None:
        """Levée **dans le fil appelant**, à l'endroit où il l'attend.

        Avalée par le fil, elle rendrait un flux vide — une analyse « terminée »
        sans un seul véhicule, et l'utilisateur chercherait le défaut dans sa vidéo.
        """

        def source() -> Iterator[int]:
            yield 0
            msg = "le décodage a lâché"
            raise RuntimeError(msg)

        stream = prefetch(source(), depth=1, name=THREAD_NAME)

        with pytest.raises(RuntimeError, match="le décodage a lâché"):
            list(stream)
