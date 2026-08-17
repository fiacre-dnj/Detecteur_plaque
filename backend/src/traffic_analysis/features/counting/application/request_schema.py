"""Schémas d'entrée du comptage — **partagés par le différé et le temps réel**.

Ces schémas vivent dans la couche `application` de `counting` et non dans l'`api`
d'une feature, pour une raison que le test d'architecture a rendue visible : le mode
différé (`jobs`) **et** le mode direct (`realtime`) valident tous les deux la même
configuration. Les laisser dans `jobs/api/` obligeait `realtime` à fouiller dans
l'`api` d'une autre feature, ce qui est précisément interdit.

Et c'est une bonne chose que ce soit interdit : la valeur de ce partage est qu'un
**même tracé donne les mêmes chiffres dans les deux modes**. Deux schémas parallèles
finiraient par divulguer une différence de validation — une borne ici, un refus
là — et le même tracé ne compterait plus pareil selon le mode choisi, sans que rien
ne l'explique.

Le miroir TypeScript de `frontend/src/shared/api/contracts.ts` reprend ces noms
**exactement** : c'est un contrat, pas une coïncidence.
"""

from __future__ import annotations

from pydantic import Field, field_validator, model_validator

from traffic_analysis.core.schemas import CamelModel
from traffic_analysis.features.counting.application.dto import (
    DETECTABLE_CLASS_IDS,
    DETECTABLE_CLASSES,
    VEHICLE_CLASS_IDS,
    AnalysisJobConfig,
    CountingLineDef,
    DirectionRole,
    Point,
    ZoneDef,
)
from traffic_analysis.features.counting.domain.pacing import (
    MAX_FPS_CAP,
    MAX_SPEED,
    MIN_FPS_CAP,
    MIN_SPEED,
)
from traffic_analysis.features.models_registry.application.catalogue_access import (
    is_known_model,
    known_model_ids,
)


class PointSchema(CamelModel):
    x: float
    y: float

    def to_domain(self) -> Point:
        return Point(self.x, self.y)


class LineSchema(CamelModel):
    """Une ligne de comptage telle que le client la dessine.

    Les quatre champs de sens décrivent, ils ne comptent pas : le serveur les
    accepte, les persiste dans la configuration du job et les rend tels quels. Un
    total ne dépend jamais d'un mot que l'utilisateur peut corriger après coup.
    """

    id: str = Field(min_length=1, max_length=64, examples=["l1"])
    name: str = Field(default="", max_length=120, examples=["Voie nord"])
    # La couleur appartient à l'interface : elle est acceptée pour que le client
    # puisse rejouer une configuration à l'identique, et n'est **jamais**
    # interprétée par le serveur.
    color: str = Field(default="", max_length=32)
    zone_id: str | None = Field(default=None, max_length=64)
    a: PointSchema
    b: PointSchema
    #: Nom du sens A→B. `""` demande à l'interface de poser son défaut géométrique,
    #: recalculé quand la ligne bouge : figer un défaut ici le collerait à
    #: l'orientation qu'avait la ligne au moment de l'envoi.
    #:
    #: Plus court que `name` (60 contre 120) parce que deux de ces libellés doivent
    #: tenir de part et d'autre d'un trait sur la vidéo, pas dans un tableau.
    positive_name: str = Field(default="", max_length=60, examples=["Vers le centre"])
    negative_name: str = Field(default="", max_length=60, examples=["Vers la rocade"])
    positive_role: DirectionRole = "neutral"
    negative_role: DirectionRole = "neutral"
    #: Longueur **réelle** du trait, en mètres. `None` = non calibrée.
    #:
    #: Contrairement aux quatre champs de sens, celle-ci **est** lue par le
    #: serveur : elle donne l'échelle pixels/mètre locale qui convertit les
    #: vitesses en km/h à la profondeur où la ligne est posée. Une longueur
    #: corrigée demande donc une réanalyse, là où un rôle corrigé ne demande rien.
    #:
    #: Bornée à 500 m : au-delà, c'est une saisie erronée (un chiffre tapé deux
    #: fois), et elle produirait des vitesses absurdement basses sans rien signaler.
    #:
    #: `length_meters` et non `length_m` : l'alias camelCase est **généré** du nom
    #: Python, et `length_m` donnerait `lengthM` — un champ que le client
    #: n'enverrait jamais, donc une calibration silencieusement ignorée.
    length_meters: float | None = Field(default=None, gt=0.0, le=500.0, examples=[7.0])

    def to_domain(self) -> CountingLineDef:
        return CountingLineDef(
            id=self.id,
            name=self.name,
            a=self.a.to_domain(),
            b=self.b.to_domain(),
            zone_id=self.zone_id,
            positive_name=self.positive_name,
            negative_name=self.negative_name,
            positive_role=self.positive_role,
            negative_role=self.negative_role,
            length_m=self.length_meters,
        )


class ZoneSchema(CamelModel):
    id: str = Field(min_length=1, max_length=64, examples=["z1"])
    name: str = Field(default="", max_length=120)
    color: str = Field(default="", max_length=32)
    points: list[PointSchema] = Field(min_length=3)

    def to_domain(self) -> ZoneDef:
        return ZoneDef(
            id=self.id, name=self.name, points=tuple(point.to_domain() for point in self.points)
        )


class AnalysisRequestSchema(CamelModel):
    """Configuration d'une analyse. Envoyée en JSON dans le champ `request`."""

    model_id: str = Field(examples=["yolov8n"])
    confidence_threshold: float = Field(0.35, ge=0.01, le=0.99)
    iou_threshold: float = Field(0.45, ge=0.05, le=0.95)
    min_hits: int = Field(2, ge=1, le=10)
    max_lost_ms: float = Field(2500, ge=200, le=15000)
    mask_outside_zones: bool = False
    frame_stride: int = Field(1, ge=1, le=10)
    detect_plates: bool = False
    plate_confidence: float | None = Field(None, ge=0.05, le=0.95)
    read_plate_text: bool = Field(
        False,
        description=(
            "Lire le texte des plaques localisées. La lecture n'a lieu que si "
            "`detectPlates` est vrai — sans boîte, il n'y a rien à lire — et que le "
            "modèle d'OCR est installé (`plateOcrAvailable`). Le texte publié est un "
            "vote sur toute la vie du véhicule, pas la lecture de l'image courante."
        ),
    )
    pixels_per_meter: float | None = Field(
        None,
        gt=0,
        description="Échelle de la scène. Sans elle, les vitesses restent en px/s.",
        examples=[12.5],
    )
    class_ids: list[int] = Field(
        default_factory=lambda: list(VEHICLE_CLASS_IDS),
        description=(
            "Classes à détecter et à compter, par identifiant COCO. Le catalogue "
            "cochable est publié par `GET /api/v1/models/classes`. Le défaut est "
            "les quatre véhicules, c'est-à-dire le comportement historique."
        ),
        examples=[[2, 3, 5, 7]],
    )
    analysis_speed: float | None = Field(
        None,
        ge=MIN_SPEED,
        le=MAX_SPEED,
        description=(
            "Cadence maximale de l'analyse, en multiples de la vitesse réelle de la "
            "scène. `null` (le défaut) n'impose aucune borne : l'analyse va aussi "
            "vite que la machine le permet. `1` la fait durer exactement le temps de "
            "la vidéo, ce qui rend l'aperçu live regardable — sans bornage, un "
            "serveur deux fois plus rapide que la scène produit un aperçu deux fois "
            "trop rapide. Sans effet en direct, où le client cadence son envoi."
        ),
        examples=[1],
    )
    max_analysis_fps: float | None = Field(
        None,
        ge=MIN_FPS_CAP,
        le=MAX_FPS_CAP,
        description=(
            "Plafond absolu de l'analyse, en images analysées par seconde réelle — "
            "indépendant de la cadence de la source. `null` (le défaut) n'impose "
            "aucune borne. Distinct de `analysisSpeed`, qui borne une vitesse "
            "*relative* au temps de la scène : les deux peuvent être posés "
            "ensemble, et le plus restrictif s'applique. Sans effet en direct."
        ),
        examples=[30],
    )
    start_ms: float = Field(
        0.0,
        ge=0.0,
        description=(
            "Début de la fenêtre analysée, en millisecondes de **temps de scène** — "
            "c'est-à-dire la position sur la barre de lecture, pas un index d'image. "
            "`0` (le défaut) analyse depuis le début. Les horodatages publiés restent "
            "absolus : une fenêtre qui démarre à 34 s date son premier franchissement "
            "à 34 s et non à 0. Sans effet en direct."
        ),
        examples=[34000],
    )
    end_ms: float | None = Field(
        None,
        gt=0.0,
        description=(
            "Fin de la fenêtre analysée, en millisecondes de temps de scène. `null` "
            "(le défaut) analyse jusqu'au bout. **Borne exclue** : deux fenêtres "
            "adjacentes ne partagent donc aucune image, et ne comptent pas deux fois "
            "ce qui se passe à leur jointure. Sans effet en direct."
        ),
        examples=[300000],
    )
    lines: list[LineSchema] = Field(default_factory=list)
    zones: list[ZoneSchema] = Field(default_factory=list)

    @field_validator("class_ids")
    @classmethod
    def _selectable_classes(cls, value: list[int]) -> list[int]:
        """Refuser une classe qu'aucun modèle du catalogue ne sait reconnaître.

        Le mode de défaillance évité est muet : une classe hors COCO — une
        charrette, un `tuk-tuk` — passerait la validation, serait transmise telle
        quelle à `classes=` d'Ultralytics, et **ne détecterait jamais rien**. Aucune
        erreur, aucun journal : juste un compteur à zéro qui se lit comme une panne
        de détection alors que c'est une demande impossible.

        Une liste vide est refusée pour la même raison : elle rendrait les 80 classes
        de COCO côté Ultralytics (`classes=[]` n'est pas un filtre vide), donc des
        piétons, des feux et des panneaux comptés comme des véhicules.

        Les doublons sont écartés en gardant l'ordre : `[2, 2, 3]` est une intention
        claire, pas une erreur qui mérite un refus.
        """
        unknown = sorted(set(value) - DETECTABLE_CLASS_IDS)
        if unknown:
            catalogue = ", ".join(f"{entry.id} ({entry.label})" for entry in DETECTABLE_CLASSES)
            msg = (
                f"Classes inconnues : {unknown}. Les modèles du catalogue sont "
                f"entraînés sur COCO et ne savent reconnaître que : {catalogue}. "
                "Une classe absente de cette liste demande un autre modèle, pas un "
                "autre réglage."
            )
            raise ValueError(msg)
        if not value:
            msg = (
                "Sélectionnez au moins une classe à compter : une liste vide ne "
                "restreindrait rien et compterait les 80 classes de COCO."
            )
            raise ValueError(msg)
        return list(dict.fromkeys(value))

    @field_validator("model_id")
    @classmethod
    def _known_model(cls, value: str) -> str:
        """Refuser ici plutôt qu'au chargement.

        Un identifiant inconnu accepté produirait un job qui échoue trente
        secondes plus tard, sans que l'utilisateur sache lequel de ses réglages
        est en cause. Le message liste les identifiants valides.
        """
        if not is_known_model(value):
            msg = (
                f"Le modèle « {value} » n'existe pas au catalogue. "
                f"Modèles valides : {', '.join(known_model_ids())}."
            )
            raise ValueError(msg)
        return value

    @model_validator(mode="after")
    def _check_geometry(self) -> AnalysisRequestSchema:
        """Quatre refus, chacun évitant une analyse dont le résultat serait vide.

        Refuser tôt et clairement vaut mieux que rendre des compteurs à zéro : un
        écran de zéros ressemble à une panne, et l'utilisateur cherche le bug au
        mauvais endroit.
        """
        line_ids = [line.id for line in self.lines]
        zone_ids = [zone.id for zone in self.zones]

        if len(set(line_ids)) != len(line_ids):
            msg = "Deux lignes portent le même identifiant."
            raise ValueError(msg)
        if len(set(zone_ids)) != len(zone_ids):
            msg = "Deux zones portent le même identifiant."
            raise ValueError(msg)

        known_zones = set(zone_ids)
        for line in self.lines:
            if line.zone_id is not None and line.zone_id not in known_zones:
                msg = (
                    f"La ligne « {line.id} » référence la zone « {line.zone_id} », "
                    "qui n'existe pas."
                )
                raise ValueError(msg)
            if line.a.x == line.b.x and line.a.y == line.b.y:
                msg = (
                    f"La ligne « {line.id} » est de longueur nulle : "
                    "elle ne compterait jamais rien."
                )
                raise ValueError(msg)

        if self.end_ms is not None and self.end_ms <= self.start_ms:
            # Cinquième refus, même famille que les quatre autres : une fenêtre vide
            # ou inversée n'analyserait aucune image et rendrait des compteurs à
            # zéro, ce qui se lit comme une panne de détection. Le message donne les
            # deux bornes, parce que l'utilisateur ne voit à l'écran que des
            # `mm:ss` et ne saurait pas laquelle des deux corriger.
            msg = (
                f"L'intervalle demandé est vide : il se termine à {self.end_ms:.0f} ms "
                f"alors qu'il commence à {self.start_ms:.0f} ms. La fin doit être "
                "strictement après le début."
            )
            raise ValueError(msg)

        if not self.lines and not self.zones:
            msg = (
                "Une analyse sans ligne ni zone ne produirait aucun compteur. "
                "Ajoutez au moins une ligne de comptage."
            )
            raise ValueError(msg)
        return self

    def to_config(self) -> AnalysisJobConfig:
        return AnalysisJobConfig(
            model_id=self.model_id,
            confidence_threshold=self.confidence_threshold,
            iou_threshold=self.iou_threshold,
            min_hits=self.min_hits,
            mask_outside_zones=self.mask_outside_zones,
            frame_stride=self.frame_stride,
            detect_plates=self.detect_plates,
            plate_confidence=self.plate_confidence,
            read_plate_text=self.read_plate_text,
            pixels_per_meter=self.pixels_per_meter,
            max_lost_ms=self.max_lost_ms,
            lines=tuple(line.to_domain() for line in self.lines),
            zones=tuple(zone.to_domain() for zone in self.zones),
            class_ids=tuple(self.class_ids),
            analysis_speed=self.analysis_speed,
            max_analysis_fps=self.max_analysis_fps,
            start_ms=self.start_ms,
            end_ms=self.end_ms,
        )
