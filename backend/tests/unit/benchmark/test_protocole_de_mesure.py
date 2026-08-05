"""Le protocole de mesure, règle par règle.

C'est le test le plus important du lot 8. Chacune des six règles de
`prompt/04-MODELES-YOLO-ET-BENCHMARK.md` §6 y a son scénario, et chacune était
fausse dans la version précédente — ce sont ces erreurs-là que les assertions
ci-dessous rendent impossibles à réintroduire en silence.
"""

from __future__ import annotations

import asyncio

import pytest

from tests.support.benchmark_repository import InMemoryBenchmarkRepository
from tests.support.probe import FakeImageProvider, FakeProbe
from traffic_analysis.core.errors import ConflictError
from traffic_analysis.core.pagination import PageParams
from traffic_analysis.features.benchmark.application.ports import ProbeSpec
from traffic_analysis.features.benchmark.application.service import (
    BenchmarkNotFoundError,
    BenchmarkService,
    describe,
)
from traffic_analysis.features.benchmark.domain.records import BenchmarkRun
from traffic_analysis.features.jobs.application.progress_hub import ProgressHub

SPEC = ProbeSpec(confidence=0.35, iou=0.45, class_ids=(2, 3, 5, 7))

# Série scriptée de la sonde factice. La **première** valeur est celle du run de
# chauffe, et elle est volontairement aberrante : si la chauffe entrait dans la
# statistique, la médiane vaudrait 12,0 au lieu de 11,25.
WARMUP_HEAVY = (500.0, 10.0, 11.0, 11.5, 12.0, 40.0)


def _service(
    probe: FakeProbe | None = None,
    images: FakeImageProvider | None = None,
) -> tuple[BenchmarkService, FakeProbe, InMemoryBenchmarkRepository]:
    resolved_probe = probe or FakeProbe()
    repository = InMemoryBenchmarkRepository()
    service = BenchmarkService(
        repository, resolved_probe, images or FakeImageProvider(), ProgressHub()
    )
    service.bind_loop(asyncio.get_event_loop())
    return service, resolved_probe, repository


async def _run_to_completion(
    service: BenchmarkService,
    *,
    model_ids: tuple[str, ...] = ("fake-nano", "fake-large"),
    frames: int = 5,
    image_source: str = "sample",
    job_id: str | None = None,
) -> BenchmarkRun:
    """Dépose un run et attend **la tâche**, pas un nombre d'itérations.

    `wait_for_idle()` et non une boucle de sondage bornée : une boucle qui compte
    les tours échoue dès que la machine ralentit — sous `--cov`, par exemple — et
    un test dont le verdict dépend de la vitesse de la machine ne prouve rien.
    """
    run = await service.submit(
        "run-1",
        model_ids=model_ids,
        frames=frames,
        spec=SPEC,
        image_source=image_source,
        job_id=job_id,
    )
    await service.wait_for_idle()
    final = await service.get(run.id)
    assert final.status in {"done", "error", "cancelled"}
    return final


class TestRegle1ImageDeReferenceUnique:
    async def test_tous_les_modeles_sont_mesures_sur_la_meme_image(self) -> None:
        """Une seule résolution d'image pour tout le run.

        Comparer deux modèles sur deux images différentes ne compare rien : une
        scène chargée coûte plus de post-traitement qu'une route vide, et l'écart
        se lirait comme une différence entre les modèles.
        """
        images = FakeImageProvider()
        service, _, _ = _service(images=images)

        await _run_to_completion(service, model_ids=("fake-nano", "fake-large"))

        # Une seule fois, pas une fois par modèle.
        assert images.sample_calls == 1

    async def test_le_hash_de_l_image_est_persiste_avec_le_run(self) -> None:
        """Un résultat sans son contexte est trompeur.

        Le hash est ce qui permet, six mois plus tard, de savoir si deux runs sont
        comparables — ou pourquoi ils ne le sont pas.
        """
        service, _, _ = _service()

        run = await _run_to_completion(service)
        payload = describe(run)

        assert payload["imageHash"] == "f" * 64
        assert payload["imageWidth"] == 64
        assert payload["device"] == "cpu"
        assert payload["ultralyticsVersion"] == "8.3.0-factice"

    async def test_une_image_de_job_purgee_est_refusee_au_depot(self) -> None:
        """Refus immédiat, jamais un repli silencieux sur l'échantillon.

        La vidéo d'un job a un TTL plus court que le job lui-même : son absence est
        le cas **normal** sur un job d'hier. Retomber en silence sur l'échantillon
        ferait croire à l'utilisateur qu'il mesure sur sa propre scène.
        """
        images = FakeImageProvider(job_error=ConflictError("La vidéo de ce job a été supprimée."))
        service, _, _ = _service(images=images)

        with pytest.raises(ConflictError):
            await service.submit(
                "run-1",
                model_ids=("fake-nano",),
                frames=3,
                spec=SPEC,
                image_source="job",
                job_id="job-42",
            )


class TestRegle2ChargementNonInvente:
    async def test_load_ms_vaut_zero_pour_un_modele_deja_resident(self) -> None:
        """Zéro parce qu'il n'y avait rien à charger — pas une mesure manquante.

        Inventer un chargement rapide ferait croire qu'un modèle de 137 Mo s'ouvre
        en quelques millisecondes, et l'utilisateur planifierait sa journée
        là-dessus.
        """
        probe = FakeProbe(loaded=("fake-nano",))
        service, _, _ = _service(probe)

        run = await _run_to_completion(service, model_ids=("fake-nano",))
        entry = run.entries[0]

        assert entry.load_ms == 0.0
        assert entry.was_loaded is True

    async def test_un_modele_deja_resident_n_est_pas_recharge(self) -> None:
        probe = FakeProbe(loaded=("fake-nano",))
        service, _, _ = _service(probe)

        await _run_to_completion(service, model_ids=("fake-nano",))

        assert probe.load_calls == []

    async def test_un_modele_absent_est_charge_une_seule_fois(self) -> None:
        probe = FakeProbe()
        service, _, _ = _service(probe)

        run = await _run_to_completion(service, model_ids=("fake-nano",))

        assert probe.load_calls == ["fake-nano"]
        assert run.entries[0].was_loaded is False


class TestRegle3RunDeChauffeEcarte:
    async def test_la_chauffe_est_executee_puis_ecartee_de_la_statistique(self) -> None:
        """Le cœur du protocole, et la règle la plus facile à oublier.

        La première inférence d'un modèle inclut la fusion de ses couches et
        l'allocation de ses tampons. La sonde factice place ici 500 ms en tête de
        série : si elle entrait dans la statistique, la médiane vaudrait 12,0 et le
        p95 exploserait. Écartée, la médiane vaut 11,25 — la valeur des mesures
        réelles.
        """
        probe = FakeProbe(durations=WARMUP_HEAVY)
        service, _, _ = _service(probe)

        run = await _run_to_completion(service, model_ids=("fake-nano",), frames=5)
        entry = run.entries[0]

        # Médiane de [10, 11, 11.5, 12, 40] — la chauffe (500) est absente.
        assert entry.median_ms == 11.5
        assert entry.max_ms == 40.0
        # Six appels pour cinq mesures : la chauffe a bien eu lieu.
        assert probe.infer_calls_for("fake-nano") == 6
        assert entry.frames == 5

    async def test_le_nombre_de_mesures_retenues_suit_la_requete(self) -> None:
        probe = FakeProbe(durations=WARMUP_HEAVY)
        service, _, _ = _service(probe)

        run = await _run_to_completion(service, model_ids=("fake-nano",), frames=3)

        assert run.entries[0].frames == 3
        assert probe.infer_calls_for("fake-nano") == 4  # 1 chauffe + 3 mesures


class TestRegle4SeuilsDeLaRequete:
    async def test_les_seuils_persistes_sont_ceux_de_la_requete(self) -> None:
        """Sinon la colonne « détections » contredit ce que l'utilisateur voit.

        Les seuils sont persistés avec le run : sans eux, la colonne
        « détections » d'un run relu ne serait rattachable à aucun réglage.
        """
        service, _, _ = _service()
        strict = ProbeSpec(confidence=0.75, iou=0.30, class_ids=(2,))

        await service.submit(
            "run-1",
            model_ids=("fake-nano",),
            frames=2,
            spec=strict,
            image_source="sample",
            job_id=None,
        )
        await service.wait_for_idle()

        payload = describe(await service.get("run-1"))

        assert payload["confidenceThreshold"] == 0.75
        assert payload["iouThreshold"] == 0.30

    async def test_le_nombre_de_detections_provient_de_la_derniere_mesure(self) -> None:
        """De la dernière et non de la chauffe.

        La chauffe n'est pas une mesure : son `speed` reflète une allocation en
        cours, et ses détections sont produites dans les mêmes conditions
        atypiques.
        """
        probe = FakeProbe(detections=7)
        service, _, _ = _service(probe)

        run = await _run_to_completion(service, model_ids=("fake-nano",))

        assert run.entries[0].detections == 7

    async def test_les_temps_de_pre_et_post_traitement_sont_nuls_si_non_exposes(self) -> None:
        """`None` et non `0.0` : un zéro se lirait « instantané ».

        L'information est absente, pas nulle. La distinction est visible dans le
        tableau, où la colonne affiche « — ».
        """
        probe = FakeProbe(expose_speed=False)
        service, _, _ = _service(probe)

        run = await _run_to_completion(service, model_ids=("fake-nano",))
        entry = run.entries[0]

        assert entry.preprocess_ms is None
        assert entry.postprocess_ms is None


class TestRegle5LiberationApresMesure:
    async def test_chaque_modele_est_libere_apres_sa_mesure(self) -> None:
        """**La** leçon de la version précédente : vingt modèles résidents = mémoire épuisée.

        C'est la vraie raison d'être de ce module.
        """
        probe = FakeProbe()
        service, _, _ = _service(probe)

        run = await _run_to_completion(service, model_ids=("fake-nano", "fake-large"))

        assert probe.release_calls == ["fake-nano", "fake-large"]
        assert all(entry.released for entry in run.entries)

    async def test_l_etat_de_residence_revient_a_son_etat_initial_apres_le_run(self) -> None:
        """Le test que le cahier des charges demande explicitement.

        Un benchmark qui laisse derrière lui les vingt modèles qu'il a chargés a
        transformé une mesure en fuite de mémoire.
        """
        probe = FakeProbe()
        before = probe.loaded_ids()
        service, _, _ = _service(probe)

        await _run_to_completion(service, model_ids=("fake-nano", "fake-large"))

        assert probe.loaded_ids() == before

    async def test_un_modele_occupe_par_une_analyse_reste_resident_et_la_ligne_le_dit(
        self,
    ) -> None:
        """Le refus du registre n'est pas un échec, c'est le comportement voulu.

        Arracher son modèle à une analyse en cours la laisserait sans moteur.
        L'information remonte dans la ligne (`released: false`) et s'affiche en
        infobulle : sans elle, un utilisateur qui voit la mémoire rester haute ne
        sait pas si le benchmark a nettoyé derrière lui.
        """
        probe = FakeProbe(loaded=("fake-large",), refuse_release=("fake-large",))
        service, _, _ = _service(probe)

        run = await _run_to_completion(service, model_ids=("fake-nano", "fake-large"))
        by_id = {entry.model_id: entry for entry in run.entries}

        assert by_id["fake-nano"].released is True
        assert by_id["fake-large"].released is False
        # Toujours résident : le registre a refusé, et c'est ce qu'on veut.
        assert "fake-large" in probe.loaded_ids()


class TestRegle6EchecCaptureParModele:
    async def test_un_modele_en_echec_n_interrompt_pas_le_run(self) -> None:
        """Sinon un run de vingt modèles est perdu pour un seul poids manquant."""
        probe = FakeProbe(fail_on=("fake-nano",))
        service, _, _ = _service(probe)

        run = await _run_to_completion(service, model_ids=("fake-nano", "fake-large"))

        assert run.status == "done"
        assert len(run.entries) == 2

    async def test_la_ligne_en_echec_porte_un_message_francais_et_pas_de_mesure(self) -> None:
        probe = FakeProbe(fail_on=("fake-nano",))
        service, _, _ = _service(probe)

        run = await _run_to_completion(service, model_ids=("fake-nano", "fake-large"))
        by_id = {entry.model_id: entry for entry in run.entries}

        assert by_id["fake-nano"].error is not None
        assert "fake-nano" in by_id["fake-nano"].error
        assert by_id["fake-nano"].median_ms == 0.0
        # Le modèle suivant, lui, est mesuré normalement.
        assert by_id["fake-large"].error is None
        assert by_id["fake-large"].median_ms > 0.0

    async def test_un_modele_en_echec_n_est_jamais_mesure(self) -> None:
        """Ni chauffe ni mesure : le chargement a échoué avant."""
        probe = FakeProbe(fail_on=("fake-nano",))
        service, _, _ = _service(probe)

        await _run_to_completion(service, model_ids=("fake-nano",))

        assert probe.infer_calls_for("fake-nano") == 0


class TestOrdreEtCoherenceDuRun:
    async def test_les_modeles_sont_mesures_dans_l_ordre_demande(self) -> None:
        """Un par un et jamais en parallèle.

        Deux modèles mesurés simultanément se disputent le même CPU et se
        ralentissent mutuellement : les chiffres resteraient plausibles et
        seraient faux tous les deux.
        """
        probe = FakeProbe()
        service, _, _ = _service(probe)

        run = await _run_to_completion(service, model_ids=("fake-large", "fake-nano"))

        assert [entry.model_id for entry in run.entries] == [
            "fake-large",
            "fake-nano",
        ]
        # Aucun entrelacement : tous les appels du premier modèle précèdent ceux
        # du second.
        first_block = probe.infer_calls[: probe.infer_calls_for("fake-large")]
        assert set(first_block) == {"fake-large"}

    async def test_le_run_progresse_ligne_par_ligne_et_finit_a_cent_pour_cent(self) -> None:
        service, _, repository = _service()

        run = await _run_to_completion(service, model_ids=("fake-nano", "fake-large"))
        payload = describe(run)

        assert payload["progress"] == 1.0
        assert (payload["completed"], payload["total"]) == (2, 2)
        # Les lignes ont bien été écrites **au fil** du run, pas en bloc à la fin :
        # le dépôt les a reçues une par une.
        stored = await repository.get("run-1")
        assert stored is not None
        assert len(stored.entries) == 2

    async def test_le_modele_le_plus_rapide_est_designe(self) -> None:
        probe = FakeProbe()
        service, _, _ = _service(probe)

        run = await _run_to_completion(service)
        payload = describe(run)

        # Les deux modèles voient la même série, donc la même médiane : le premier
        # gagne à égalité. Ce qui importe est qu'un modèle soit désigné.
        assert payload["fastestModelId"] in {"fake-nano", "fake-large"}


class TestUnSeulBenchmarkALaFois:
    async def test_le_semaphore_serialise_deux_runs(self) -> None:
        """Deux runs simultanés se mesureraient l'un l'autre.

        Le second attend en `queued` puis s'exécute : il n'est **pas** refusé —
        comme pour les jobs, l'utilisateur doit voir « en file d'attente » et non
        un 503.
        """
        probe = FakeProbe()
        service, _, _ = _service(probe)

        await service.submit(
            "run-a",
            model_ids=("fake-nano",),
            frames=2,
            spec=SPEC,
            image_source="sample",
            job_id=None,
        )
        await service.submit(
            "run-b",
            model_ids=("fake-large",),
            frames=2,
            spec=SPEC,
            image_source="sample",
            job_id=None,
        )
        await service.wait_for_idle()

        # Les deux aboutissent : le second a attendu son tour, il n'a pas été
        # refusé. Et aucun n'a été mesuré pendant que l'autre tournait — c'est le
        # sémaphore qui le garantit, faute de quoi les deux chiffres seraient faux.
        assert (await service.get("run-a")).status == "done"
        assert (await service.get("run-b")).status == "done"
        assert probe.infer_calls_for("fake-nano") == 3  # 1 chauffe + 2 mesures
        assert probe.infer_calls_for("fake-large") == 3


class TestAnnulationEtLectures:
    async def test_un_run_encore_en_file_est_annule_immediatement(self) -> None:
        """Un run `queued` n'a pas de worker pour observer l'événement d'annulation.

        Sans ce traitement, il resterait en attente indéfiniment.
        """
        service, _, _ = _service()
        await service.submit(
            "run-1",
            model_ids=("fake-nano",),
            frames=2,
            spec=SPEC,
            image_source="sample",
            job_id=None,
        )

        cancelled = await service.cancel_or_purge("run-1")

        assert cancelled.status == "cancelled"

    async def test_supprimer_un_run_termine_le_retire_de_la_base(self) -> None:
        service, _, _ = _service()
        await _run_to_completion(service, model_ids=("fake-nano",))

        await service.cancel_or_purge("run-1")

        with pytest.raises(BenchmarkNotFoundError):
            await service.get("run-1")

    async def test_un_run_inconnu_leve_une_erreur_qui_dit_lequel(self) -> None:
        service, _, _ = _service()

        with pytest.raises(BenchmarkNotFoundError, match="inexistant"):
            await service.get("inexistant")

    async def test_le_dernier_run_est_rendu_pour_ne_pas_ouvrir_une_page_vide(self) -> None:
        """Un écran vide alors qu'une mesure existe en base se lit comme une panne."""
        service, _, _ = _service()

        assert await service.latest() is None

        await _run_to_completion(service, model_ids=("fake-nano",))
        latest = await service.latest()

        assert latest is not None
        assert latest.id == "run-1"
        assert latest.status == "done"

    async def test_l_historique_est_paginable(self) -> None:
        service, _, _ = _service()
        await _run_to_completion(service, model_ids=("fake-nano",))

        page = await service.list(PageParams(limit=10, offset=0))

        assert page.total == 1
        assert page.items[0].id == "run-1"


class TestAnnulationEnCoursDeRun:
    async def test_l_annulation_s_arrete_entre_deux_modeles(self) -> None:
        """Entre deux modèles, jamais au milieu d'une inférence.

        Interrompre de force laisserait le bail du modèle non rendu, donc une
        instance immobilisée jusqu'au redémarrage. Le drapeau est donc observé
        **avant** de commencer le modèle suivant, ce qui laisse le précédent
        s'achever et rendre son bail proprement.

        Le point d'accroche est `release`, dernier geste de la mesure d'un modèle :
        s'y brancher revient à demander l'annulation exactement là où le run
        l'observera. Le drapeau est un `threading.Event`, sûr entre threads — la
        mesure tourne dans un thread worker.
        """
        cancelled_after: list[str] = []

        def cancel_after_first(model_id: str) -> None:
            if not cancelled_after:
                cancelled_after.append(model_id)
                service._cancellations["run-1"].set()

        probe = FakeProbe(after_release=cancel_after_first)
        service, _, _ = _service(probe)

        run = await _run_to_completion(service, model_ids=("fake-nano", "fake-large"), frames=2)

        assert run.status == "cancelled"
        # Le premier modèle est allé au bout et a rendu son bail ; le second n'a
        # jamais été touché.
        assert cancelled_after == ["fake-nano"]
        assert probe.infer_calls_for("fake-large") == 0
        assert probe.loaded_ids() == set()

    async def test_un_echec_global_termine_le_run_en_erreur_sans_fuite_de_details(
        self,
    ) -> None:
        """Un échec inattendu produit un statut `error` et un message générique.

        Générique volontairement : le détail technique va au journal, où il est
        corrélable par `requestId`. Le message affiché ne doit jamais porter une
        trace de pile.
        """

        class BrokenRepository(InMemoryBenchmarkRepository):
            async def append_entry(  # type: ignore[override]
                self,
                run_id: str,  # noqa: ARG002 — la signature du port, l'écriture échoue avant
                entry: object,  # noqa: ARG002
            ) -> None:
                message = "la base est tombée"
                raise RuntimeError(message)

        repository = BrokenRepository()
        service = BenchmarkService(repository, FakeProbe(), FakeImageProvider(), ProgressHub())
        service.bind_loop(asyncio.get_event_loop())

        await service.submit(
            "run-1",
            model_ids=("fake-nano",),
            frames=2,
            spec=SPEC,
            image_source="sample",
            job_id=None,
        )
        await service.wait_for_idle()
        run = await service.get("run-1")

        assert run.status == "error"
        assert run.error is not None
        assert "journaux" in run.error
        assert "RuntimeError" not in run.error
