"""Persistance SQLite : PRAGMA, cascades, insertion en lot, purge, exports.

Base **en fichier temporaire** et non `:memory:` : les connexions multiples d'un
moteur async ne partagent pas une base mémoire, donc la moitié des tests
verraient un schéma vide. Le fichier est détruit par la fixture `tmp_path`.

Les migrations sont appliquées **par Alembic**, jamais par `create_all` : une
migration cassée doit être vue par les tests, et c'est la moitié de leur intérêt.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from time import perf_counter
from typing import TYPE_CHECKING, Any

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from traffic_analysis.core.db.engine import create_engine, create_session_factory
from traffic_analysis.core.db.migrations import run_migrations
from traffic_analysis.core.pagination import PageParams
from traffic_analysis.core.settings import Settings
from traffic_analysis.features.counting.application.dto import AnalysisResultData, Progress
from traffic_analysis.features.counting.domain.models import (
    AnalysisStats,
    CrossingEvent,
    LineCrossing,
    LineTally,
    VehicleRecord,
    VideoInfo,
    ZoneEntryEvent,
)
from traffic_analysis.features.jobs.application.ports import JobFilters
from traffic_analysis.features.jobs.domain.records import JobRecord, VideoMetadata
from traffic_analysis.features.jobs.infrastructure.sqlalchemy_repository import (
    SqlAlchemyJobRepository,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from pathlib import Path

    from sqlalchemy.ext.asyncio import AsyncEngine

NOW = datetime(2026, 8, 5, 10, 0, tzinfo=UTC)


@pytest.fixture
async def db_engine(tmp_path: Path) -> AsyncIterator[AsyncEngine]:
    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        env="test",
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'test.db'}",
    )
    engine = create_engine(settings)
    await run_migrations(engine)
    yield engine
    await engine.dispose()


@pytest.fixture
def repository(db_engine: AsyncEngine) -> SqlAlchemyJobRepository:
    return SqlAlchemyJobRepository(create_session_factory(db_engine))


def _job(job_id: str = "job-1", **overrides: Any) -> JobRecord:  # noqa: ANN401
    defaults: dict[str, Any] = {
        "id": job_id,
        "status": "queued",
        "model_id": "yolov8n",
        "file_name": "carrefour.mp4",
        "file_size_bytes": 4096,
        "created_at": NOW,
        "config_json": {"modelId": "yolov8n"},
    }
    defaults.update(overrides)
    return JobRecord(**defaults)


def _result(job_id: str = "job-1", *, vehicles: int = 3, crossings: int = 5) -> AnalysisResultData:
    data = AnalysisResultData(
        job_id=job_id,
        model_id="yolov8n",
        video=VideoInfo(1920, 1080, 25.0, 500),
        processing_fps=12.5,
    )
    data.vehicles = tuple(
        VehicleRecord(
            global_id=index + 1,
            label="car" if index % 2 == 0 else "truck",
            first_seen_ms=index * 100.0,
            last_seen_ms=index * 100.0 + 4000.0,
            crossed_lines=(LineCrossing("l1", 1, index * 100.0 + 500.0),),
            zones_visited=("z1",),
            reid_count=index % 2,
            avg_speed_px_s=120.0 + index,
            avg_speed_kmh=None,
            best_plate_score=0.7 if index == 0 else None,
        )
        for index in range(vehicles)
    )
    data.crossings = [
        CrossingEvent(
            line_id="l1",
            global_id=index % max(vehicles, 1) + 1,
            track_id=index + 1,
            label="car",
            direction=1 if index % 2 == 0 else -1,
            timestamp_ms=index * 250.0,
            frame_index=index * 5,
        )
        for index in range(crossings)
    ]
    data.zone_events = [
        ZoneEntryEvent(zone_id="z1", global_id=1, label="car", timestamp_ms=100.0, frame_index=2)
    ]
    data.stats = AnalysisStats(
        unique_vehicles=vehicles,
        unique_by_class={"car": vehicles},
        crossings=crossings,
        by_class={"car": crossings},
        by_line={
            "l1": LineTally(total=crossings, by_class={"car": crossings}, positive=3, negative=2)
        },
        by_zone={},
        reid_hits=1,
        vehicles_per_minute=24.0,
        active_tracks=0,
        elapsed_ms=20000.0,
        analysed_scene_ms=20000.0,
    )
    return data


class TestPragmas:
    async def test_les_cles_etrangeres_sont_reellement_actives(
        self, db_engine: AsyncEngine
    ) -> None:
        """Le piège 47 de prompt/13, vérifié plutôt que supposé.

        SQLite désactive les clés étrangères **par défaut**. Sans le PRAGMA, les
        cascades ne s'appliquent pas et les orphelins s'accumulent en silence : on
        supprime un job, ses cinq mille franchissements restent.

        Le test insère un franchissement orphelin. Il **doit** échouer.
        """
        async with db_engine.begin() as connection:
            assert (await connection.execute(text("PRAGMA foreign_keys"))).scalar() == 1

            with pytest.raises(IntegrityError):
                await connection.execute(
                    text(
                        "INSERT INTO job_crossings "
                        "(job_id, line_id, global_id, track_id, label, direction, "
                        " timestamp_ms, frame_index) "
                        "VALUES ('job-fantome', 'l1', 1, 1, 'car', 1, 0.0, 0)"
                    )
                )

    async def test_le_mode_wal_est_actif(self, db_engine: AsyncEngine) -> None:
        """WAL permet de consulter l'historique pendant qu'une analyse écrit."""
        async with db_engine.begin() as connection:
            mode = (await connection.execute(text("PRAGMA journal_mode"))).scalar()
        assert str(mode).lower() == "wal"


class TestCycleDeVie:
    async def test_un_job_survit_et_se_relit_a_l_identique(
        self, repository: SqlAlchemyJobRepository
    ) -> None:
        await repository.add(_job())

        stored = await repository.get("job-1")

        assert stored is not None
        assert stored.model_id == "yolov8n"
        assert stored.file_name == "carrefour.mp4"
        assert stored.config_json == {"modelId": "yolov8n"}
        assert stored.created_at == NOW

    async def test_un_job_survit_a_un_redemarrage_du_service(self, db_engine: AsyncEngine) -> None:
        """LE test de la persistance : une nouvelle session, un nouveau dépôt.

        C'est la promesse de tout le lot — sans elle, un redémarrage pendant une
        soirée d'analyses effacerait l'historique.
        """
        first = SqlAlchemyJobRepository(create_session_factory(db_engine))
        await first.add(_job("survivant"))

        second = SqlAlchemyJobRepository(create_session_factory(db_engine))
        assert (await second.get("survivant")) is not None

    async def test_la_progression_se_met_a_jour(self, repository: SqlAlchemyJobRepository) -> None:
        await repository.add(_job())

        await repository.update_progress("job-1", Progress(120, 500, 14.2))

        stored = await repository.get("job-1")
        assert stored is not None
        assert stored.processed_frames == 120
        assert stored.total_frames == 500
        assert stored.progress == pytest.approx(0.24)

    async def test_un_job_termine_affiche_cent_pour_cent(
        self, repository: SqlAlchemyJobRepository
    ) -> None:
        """La barre doit atteindre sa fin, sinon l'analyse paraît interrompue."""
        await repository.add(_job())
        await repository.set_status("job-1", "running")
        await repository.set_status("job-1", "done")

        stored = await repository.get("job-1")
        assert stored is not None
        assert stored.progress == 1.0
        assert stored.started_at is not None
        assert stored.finished_at is not None

    async def test_started_at_n_est_pas_ecrase(self, repository: SqlAlchemyJobRepository) -> None:
        """Sinon la durée affichée dans l'historique deviendrait fausse."""
        await repository.add(_job())
        await repository.set_status("job-1", "running")
        first_start = (await repository.get("job-1")).started_at  # type: ignore[union-attr]

        await repository.set_status("job-1", "running")

        assert (await repository.get("job-1")).started_at == first_start  # type: ignore[union-attr]

    async def test_les_metadonnees_video_sont_enregistrees(
        self, repository: SqlAlchemyJobRepository
    ) -> None:
        await repository.add(_job())

        await repository.set_video_metadata("job-1", VideoMetadata(1920, 1080, 25.0, 750, 30000.0))

        stored = await repository.get("job-1")
        assert stored is not None
        assert stored.video.width == 1920
        assert stored.video.duration_ms == 30000.0


class TestAgregats:
    async def test_les_agregats_sont_ecrits_et_relus(
        self, repository: SqlAlchemyJobRepository
    ) -> None:
        await repository.add(_job())
        await repository.save_result_aggregates("job-1", _result())

        stored = await repository.get("job-1")
        assert stored is not None
        assert stored.unique_vehicles == 3
        assert stored.crossings_total == 5
        assert stored.stats_json is not None

        vehicles = await repository.list_vehicles("job-1", PageParams())
        assert vehicles.total == 3
        assert vehicles.items[0]["globalId"] == 1
        assert vehicles.items[0]["crossedLines"][0]["lineId"] == "l1"

        crossings = await repository.list_crossings("job-1", PageParams())
        assert crossings.total == 5
        # Ordre chronologique : la relecture le suppose.
        timestamps = [item["timestampMs"] for item in crossings.items]
        assert timestamps == sorted(timestamps)

    async def test_cinq_mille_franchissements_s_inserent_en_moins_d_une_seconde(
        self, repository: SqlAlchemyJobRepository
    ) -> None:
        """L'insertion en lot, mesurée.

        Un par un, cinq mille lignes prennent des minutes sur SQLite. C'est
        exactement le genre de régression qui passe inaperçue en développement,
        où les clips de test font dix secondes.
        """
        await repository.add(_job())

        started = perf_counter()
        await repository.save_result_aggregates("job-1", _result(vehicles=200, crossings=5000))
        elapsed = perf_counter() - started

        assert (await repository.list_crossings("job-1", PageParams())).total == 5000
        assert elapsed < 1.0, f"insertion en lot trop lente : {elapsed:.2f} s"

    async def test_les_deux_sens_de_la_meme_identite_coexistent(
        self, repository: SqlAlchemyJobRepository
    ) -> None:
        """**Aucune contrainte d'unicité** sur les franchissements.

        Un aller-retour réel produit deux lignes pour la même identité sur la même
        ligne. Une contrainte SQL casserait ce cas légitime — la déduplication est
        une règle de domaine, déjà appliquée en amont.
        """
        await repository.add(_job())
        data = _result(crossings=0)
        data.crossings = [
            CrossingEvent("l1", 1, 1, "car", 1, 1000.0, 25),
            CrossingEvent("l1", 1, 1, "car", -1, 5000.0, 125),
        ]
        await repository.save_result_aggregates("job-1", data)

        assert (await repository.list_crossings("job-1", PageParams())).total == 2

    async def test_supprimer_un_job_supprime_ses_agregats_en_cascade(
        self, repository: SqlAlchemyJobRepository, db_engine: AsyncEngine
    ) -> None:
        await repository.add(_job())
        await repository.save_result_aggregates("job-1", _result())

        await repository.delete("job-1")

        async with db_engine.begin() as connection:
            for table in ("job_vehicles", "job_crossings", "job_zone_events"):
                remaining = (
                    await connection.execute(text(f"SELECT COUNT(*) FROM {table}"))  # noqa: S608
                ).scalar()
                assert remaining == 0, f"orphelins dans {table}"


class TestFiltresEtPagination:
    async def test_l_historique_est_trie_du_plus_recent(
        self, repository: SqlAlchemyJobRepository
    ) -> None:
        for index in range(3):
            await repository.add(_job(f"job-{index}", created_at=NOW + timedelta(minutes=index)))

        page = await repository.list(JobFilters(), PageParams(limit=10))

        assert [job.id for job in page.items] == ["job-2", "job-1", "job-0"]

    async def test_la_pagination_borne_la_fenetre(
        self, repository: SqlAlchemyJobRepository
    ) -> None:
        for index in range(5):
            await repository.add(_job(f"job-{index}", created_at=NOW + timedelta(minutes=index)))

        page = await repository.list(JobFilters(), PageParams(limit=2, offset=1))

        assert page.total == 5
        assert [job.id for job in page.items] == ["job-3", "job-2"]

    async def test_les_filtres_se_combinent(self, repository: SqlAlchemyJobRepository) -> None:
        await repository.add(_job("a", model_id="yolo11m", status="done"))
        await repository.add(_job("b", model_id="yolo11m", status="error"))
        await repository.add(_job("c", model_id="yolov8n", status="done"))

        page = await repository.list(JobFilters(status="done", model_id="yolo11m"), PageParams())

        assert [job.id for job in page.items] == ["a"]

    async def test_le_registre_se_filtre_par_classe_et_par_plaque(
        self, repository: SqlAlchemyJobRepository
    ) -> None:
        await repository.add(_job())
        await repository.save_result_aggregates("job-1", _result(vehicles=4))

        cars = await repository.list_vehicles("job-1", PageParams(), label="car")
        with_plate = await repository.list_vehicles("job-1", PageParams(), has_plate=True)

        assert cars.total == 2
        assert with_plate.total == 1

    async def test_les_franchissements_se_filtrent_par_sens_et_par_fenetre(
        self, repository: SqlAlchemyJobRepository
    ) -> None:
        await repository.add(_job())
        await repository.save_result_aggregates("job-1", _result(crossings=6))

        positive = await repository.list_crossings("job-1", PageParams(), direction=1)
        window = await repository.list_crossings("job-1", PageParams(), from_ms=500.0, to_ms=1000.0)

        assert positive.total == 3
        assert all(item["direction"] == 1 for item in positive.items)
        assert all(500.0 <= item["timestampMs"] <= 1000.0 for item in window.items)


class TestPurgeTtl:
    async def test_seuls_les_jobs_terminaux_perimes_sont_candidats(
        self, repository: SqlAlchemyJobRepository
    ) -> None:
        vieux = datetime.now(UTC) - timedelta(hours=3)
        await repository.add(_job("termine-vieux"))
        await repository.set_status("termine-vieux", "running")
        await repository.set_status("termine-vieux", "done")
        # `set_status` date la fin de maintenant : on la recule à la main.
        #
        # La valeur est liée en **chaîne ISO** et non en `datetime` : le SQL brut
        # court-circuite le `TypeDecorator`, donc un datetime tomberait sur
        # l'adaptateur `sqlite3` par défaut — déprécié depuis Python 3.12 et
        # justement ce que `UtcDateTime` existe pour éviter.
        async with repository._session_factory() as session, session.begin():
            await session.execute(
                text("UPDATE jobs SET finished_at = :moment WHERE id = 'termine-vieux'"),
                {"moment": vieux.isoformat()},
            )

        await repository.add(_job("en-cours"))
        await repository.set_status("en-cours", "running")

        expired = await repository.list_expired(older_than_minutes=60)

        assert [job.id for job in expired] == ["termine-vieux"]
