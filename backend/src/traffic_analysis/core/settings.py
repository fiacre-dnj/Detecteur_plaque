"""Configuration du service — un seul objet, chargé une fois, injecté partout.

Interdiction de lire `os.environ` ailleurs dans le code : une valeur de
configuration lue à deux endroits finit toujours par diverger entre les deux, et
un test ne peut pas la remplacer.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal, Self

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["development", "staging", "test", "production"]
LogFormat = Literal["console", "json"]


class Settings(BaseSettings):
    """Toutes les variables d'environnement du service, préfixées `TRAFFIC_`.

    Les valeurs par défaut sont celles du développement local. Le fichier
    `.env.example` est committé et documente chaque champ ; `.env` est ignoré.
    """

    model_config = SettingsConfigDict(
        env_prefix="TRAFFIC_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="forbid",  # une variable TRAFFIC_ mal orthographiée doit être vue
        frozen=True,  # la configuration ne change pas en cours d'exécution
    )

    # ── Exécution ────────────────────────────────────────────────────────────
    env: Environment = "development"
    host: str = "127.0.0.1"
    port: int = Field(8000, ge=1, le=65535)

    # ── Journalisation ───────────────────────────────────────────────────────
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    log_format: LogFormat = "console"

    # ── CORS et hôtes ────────────────────────────────────────────────────────
    # `localhost` et `127.0.0.1` sont DEUX origines distinctes pour le
    # navigateur : les deux doivent être listées, sinon « ça marche sur l'une et
    # pas sur l'autre » (piège 46 de prompt/13).
    cors_origins: tuple[str, ...] = (
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    )
    cors_origin_regex: str | None = None
    cors_allow_credentials: bool = False
    trusted_hosts: tuple[str, ...] = ("localhost", "127.0.0.1")

    # ── Persistance ──────────────────────────────────────────────────────────
    database_url: str = "sqlite+aiosqlite:///./data/traffic.db"
    data_dir: Path = Path("./data")

    # ── Modèles ──────────────────────────────────────────────────────────────
    weights_dir: Path = Path("./.weights")
    device: str = "auto"  # auto | cpu | 0 | cuda:0
    half: bool = True  # ignoré hors GPU : en fp16 sur CPU, l'inférence ralentit
    default_model_id: str = "yolov8n"
    #: Préchauffe le modèle par défaut au démarrage, **si son poids est déjà sur le
    #: disque**. Le premier appel d'un modèle paie son chargement et sa fusion de
    #: couches, ce qui se lit comme un blocage de plusieurs dizaines de secondes.
    #:
    #: La condition « déjà téléchargé » n'est pas négociable : préchauffer un modèle
    #: absent déclencherait un téléchargement de 137 Mo au démarrage, donc un
    #: conteneur qui semble bloqué et un healthcheck qui échoue. Le service ne doit
    #: jamais dépendre du réseau pour démarrer.
    warmup: bool = True
    max_loaded_models: int = Field(2, ge=1, le=8)
    plate_model_path: Path | None = None  # vide = <weights_dir>/license-plate.onnx
    plate_confidence: float = Field(0.25, ge=0.05, le=0.95)
    # Utilisés par scripts/fetch_plate_model.py uniquement. Le service ne
    # télécharge jamais de lui-même : un démarrage ne doit pas dépendre du réseau.
    plate_model_url: str | None = None
    plate_model_sha256: str | None = None

    # ── Bornes d'exécution ───────────────────────────────────────────────────
    # Un GPU = une analyse à la fois. Les suivantes attendent en file et sont
    # acceptées en 202 « queued », jamais refusées en 503.
    max_concurrent_jobs: int = Field(1, ge=1, le=8)
    max_realtime_sessions: int = Field(1, ge=1, le=4)
    max_upload_mb: int = Field(800, ge=1, le=8192)
    job_ttl_minutes: int = Field(1440, ge=1)
    # La vidéo d'entrée est la donnée la plus lourde et la plus sensible, et elle
    # n'est plus nécessaire une fois le résultat produit : elle part plus tôt.
    input_ttl_minutes: int = Field(60, ge=1)

    # ── Limitation de débit, par adresse IP ──────────────────────────────────
    #: Limite globale. `0` la désactive entièrement — utile pour un déploiement
    #: derrière une passerelle qui limite déjà, où compter deux fois n'aiderait
    #: personne.
    rate_limit_per_minute: int = Field(60, ge=0)
    #: Dépôts d'analyse par minute. Beaucoup plus strict que la limite globale :
    #: chaque dépôt écrit un fichier de plusieurs centaines de mégaoctets sur le
    #: disque **avant** toute borne de concurrence, donc une rafale remplit le
    #: volume sans jamais saturer le GPU.
    rate_limit_jobs_per_minute: int = Field(10, ge=0)
    #: Benchmarks par heure. Un run mesure jusqu'à vingt modèles et les télécharge
    #: au besoin : c'est l'opération la plus coûteuse du service, et de loin.
    rate_limit_benchmark_per_hour: int = Field(2, ge=0)
    #: Handshakes WebSocket par minute. Le middleware CORS ne voit jamais passer un
    #: handshake, donc cette limite est la seule protection de cette porte.
    rate_limit_realtime_per_minute: int = Field(10, ge=0)

    # ── Documentation ────────────────────────────────────────────────────────
    docs_enabled: bool = True
    #: Autorise la documentation ouverte **en production**, où elle est refusée par
    #: défaut. Un second réglage plutôt qu'un simple `docs_enabled=true` : publier
    #: le schéma OpenAPI d'un service exposé est un choix qui mérite d'être écrit
    #: quelque part, pas hérité d'un `.env` de développement copié en production.
    docs_public: bool = False
    static_dir: Path | None = None  # build frontend servi par le backend

    # ── Champs dérivés ───────────────────────────────────────────────────────

    @property
    def is_production(self) -> bool:
        return self.env == "production"

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    @property
    def resolved_plate_model_path(self) -> Path:
        """Chemin effectif du modèle de plaques.

        Vide dans l'environnement signifie « à l'emplacement par défaut », pas
        « pas de modèle » : l'absence du fichier se constate au chargement, elle
        ne se déduit pas d'une configuration vide.
        """
        return self.plate_model_path or self.weights_dir / "license-plate.onnx"

    # ── Validation ───────────────────────────────────────────────────────────

    @field_validator("cors_origins", "trusted_hosts", mode="before")
    @classmethod
    def _split_comma_separated(cls, value: object) -> object:
        """Accepte aussi bien `["a","b"]` (JSON) que `a,b` (liste simple).

        La forme JSON est celle de `.env.example`, mais une variable posée à la
        main dans un shell ou un `docker run -e` prend presque toujours la forme
        séparée par des virgules. Refuser la seconde ne protège de rien.
        """
        if isinstance(value, str) and not value.lstrip().startswith("["):
            return tuple(part.strip() for part in value.split(",") if part.strip())
        return value

    @field_validator("cors_origins")
    @classmethod
    def _reject_wildcard_origin(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        """`*` n'est jamais une origine acceptable ici.

        La liste est explicite en production comme en développement. En
        développement la voie normale est le proxy Vite (donc same-origin), et
        CORS n'est que le filet pour les appels directs.
        """
        if "*" in value:
            msg = (
                "TRAFFIC_CORS_ORIGINS ne doit jamais contenir '*' : "
                "listez les origines explicitement (voir prompt/06 §2)."
            )
            raise ValueError(msg)
        return value

    @field_validator("cors_origin_regex")
    @classmethod
    def _require_anchored_regex(cls, value: str | None) -> str | None:
        """La regex d'origine doit être ancrée aux DEUX bouts.

        Sans ancrage, `https://evil.com/#mon-domaine.dev` satisfait une regex
        censée n'autoriser que `*.mon-domaine.dev`.
        """
        if not value:
            return None
        if not (value.startswith("^") and value.endswith("$")):
            msg = (
                "TRAFFIC_CORS_ORIGIN_REGEX doit être ancrée par ^ et $ : sans cela "
                "une origine hostile peut la satisfaire par son fragment."
            )
            raise ValueError(msg)
        return value

    @model_validator(mode="after")
    def _reject_credentials_with_open_cors(self) -> Self:
        """`allow_credentials` avec une origine ouverte est refusé au démarrage.

        Le navigateur refuse déjà la combinaison `Allow-Credentials: true` +
        `Allow-Origin: *`. Échouer au boot vaut mieux qu'un comportement
        inexplicable en production.
        """
        if self.cors_allow_credentials and not self.cors_origins and not self.cors_origin_regex:
            msg = (
                "TRAFFIC_CORS_ALLOW_CREDENTIALS=true exige une liste d'origines "
                "explicite ou une regex ancrée."
            )
            raise ValueError(msg)
        return self

    @model_validator(mode="after")
    def _require_json_logs_in_production(self) -> Self:
        """En production, les journaux vont à un collecteur, pas à un terminal.

        Séparé de la règle sur les docs depuis le lot 14. Les deux vivaient dans un
        seul validateur nommé `_warn_free_docs_in_production` dont le corps testait
        `is_production and docs_enabled and log_format != "json"` : la contrainte
        sur les journaux **disparaissait** dès qu'on fermait les docs, ce qui est
        exactement l'inverse du lien que le nom suggérait. Une règle qui dépend
        d'une autre sans raison est une règle qu'on finit par violer sans le voir.
        """
        if self.is_production and self.log_format != "json":
            msg = (
                "En production, TRAFFIC_LOG_FORMAT doit valoir 'json' "
                "(les journaux sont destinés à un collecteur, pas à un terminal)."
            )
            raise ValueError(msg)
        return self

    @model_validator(mode="after")
    def _refuse_public_docs_in_production(self) -> Self:
        """Un `openapi.json` public expose la surface d'attaque complète.

        Refusé, et non simplement signalé. Le défaut `docs_enabled = True` sert le
        développement, où il est juste ; le laisser passer en production
        publierait chaque route, chaque schéma et chaque borne de validation à qui
        demande — une carte du service offerte à qui cherche par où entrer.

        Ce n'est pas irrévocable : exposer sa documentation est un choix légitime
        pour une API publique. Mais il doit être **explicite**, et
        `TRAFFIC_DOCS_ENABLED=true` posé à la main en production l'est ; le défaut
        hérité d'un fichier `.env` de développement ne l'est pas. Le message dit
        les deux issues.
        """
        if self.is_production and self.docs_enabled and not self.docs_public:
            msg = (
                "En production, la documentation de l'API est fermée par défaut. "
                "Posez TRAFFIC_DOCS_ENABLED=false, ou TRAFFIC_DOCS_PUBLIC=true si "
                "vous voulez délibérément publier le schéma OpenAPI."
            )
            raise ValueError(msg)
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Configuration du processus, construite une seule fois.

    Le cache est ce qui garantit qu'il n'existe qu'un objet `Settings` : les
    tests le vident (`get_settings.cache_clear()`) ou passent leur propre
    instance à `create_app()`, ils ne rechargent jamais l'environnement.
    """
    return Settings()
