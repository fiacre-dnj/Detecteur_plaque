"""Vocabulaire du benchmark : un run, ses lignes, et la statistique d'un échantillon.

Ce module est **pur** : pas de mesure, pas d'horloge, pas de modèle. Il décrit ce
qu'est un résultat de benchmark et comment on résume une série de durées. C'est
justement cette pureté qui permet de tester le protocole de mesure sans matériel.

Deux décisions y sont écrites une fois pour toutes, parce qu'elles sont la
différence entre un chiffre exploitable et un chiffre décoratif :

1. **On résume par la médiane, pas par la moyenne.** Une série de cinq inférences
   contient presque toujours une valeur aberrante — un ordonnancement du système,
   un thermal throttle, un ramasse-miettes. La moyenne la propage à tout le
   chiffre affiché ; la médiane l'ignore. Le `p95` est là pour que l'aberration
   reste **visible** au lieu d'être perdue.
2. **Un échec est une valeur du modèle, pas une exception du run.** Une ligne
   porte son `error` et le run continue : un benchmark de vingt modèles qui
   s'arrête au troisième parce qu'un poids ne se télécharge pas n'a mesuré rien du
   tout.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

# Statuts d'un run. Volontairement les mêmes mots que ceux d'un job d'analyse :
# le frontend branche sur le même vocabulaire, et un statut qui ne veut pas dire
# la même chose d'un écran à l'autre est une source d'erreur permanente.
BenchmarkStatus = Literal["queued", "running", "done", "error", "cancelled"]

TERMINAL_STATUSES: frozenset[BenchmarkStatus] = frozenset({"done", "error", "cancelled"})

# Origine de l'image de référence.
ImageSource = Literal["sample", "job"]


def is_terminal(status: BenchmarkStatus) -> bool:
    return status in TERMINAL_STATUSES


def median(values: list[float]) -> float:
    """Médiane d'une série non vide, sur une copie triée.

    Écrite ici plutôt qu'empruntée à `statistics` pour une raison de contrat :
    cette fonction doit rendre `0.0` sur une série vide et non lever, parce qu'une
    ligne en échec n'a aucune mesure et doit tout de même pouvoir être sérialisée.
    """
    if not values:
        return 0.0
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2 == 1:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2.0


def percentile(values: list[float], fraction: float) -> float:
    """Centile par interpolation linéaire entre les deux rangs voisins.

    Le rang est calculé sur `n - 1` (méthode dite « linéaire » de numpy) : sur
    cinq mesures, le p95 tombe entre la quatrième et la cinquième valeur au lieu
    de désigner brutalement la dernière. Sans interpolation, `p95` et `max`
    seraient le même nombre pour toute série de moins de vingt points, et la
    colonne « p95 » n'apprendrait rien.
    """
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = fraction * (len(ordered) - 1)
    lower = int(rank)
    upper = min(lower + 1, len(ordered) - 1)
    weight = rank - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


@dataclass(frozen=True, slots=True)
class BenchmarkEntry:
    """Le résultat d'un modèle : une ligne du tableau.

    `load_ms` vaut **0 quand le modèle était déjà résident**. Ce n'est pas une
    mesure manquante déguisée en zéro : c'est la vérité — il n'y a rien eu à
    charger. Inventer un chargement rapide ferait croire qu'un modèle de 137 Mo
    s'ouvre en 4 ms, et l'utilisateur planifierait sa journée là-dessus.

    `released` dit si l'instance a été libérée après sa mesure. C'est affiché en
    infobulle : sans cette information, un utilisateur qui voit la mémoire
    remonter ne sait pas si le benchmark a nettoyé derrière lui.
    """

    model_id: str
    label: str
    tier: str
    # Durées en millisecondes. `median_ms` est la valeur à afficher, `p95_ms`
    # celle qui révèle l'irrégularité que la médiane a écartée.
    load_ms: float = 0.0
    median_ms: float = 0.0
    p95_ms: float = 0.0
    min_ms: float = 0.0
    max_ms: float = 0.0
    # Rapportés seulement si Ultralytics les expose (`result.speed`) : sur un
    # moteur qui ne les donne pas, `None` est honnête et `0.0` mentirait.
    preprocess_ms: float | None = None
    postprocess_ms: float | None = None
    detections: int = 0
    frames: int = 0
    was_loaded: bool = False
    released: bool = False
    # Message français destiné à l'utilisateur, jamais une trace de pile.
    error: str | None = None

    @property
    def failed(self) -> bool:
        return self.error is not None

    @property
    def fps(self) -> float:
        """Cadence déduite de la médiane — la seule cohérente avec l'affichage.

        Déduite et non mesurée séparément : deux nombres censés dire la même
        chose finissent toujours par se contredire, et l'utilisateur ne sait
        alors plus lequel croire (invariant 3 du projet).
        """
        if self.median_ms <= 0.0:
            return 0.0
        return 1000.0 / self.median_ms

    @classmethod
    def from_samples(
        cls,
        *,
        model_id: str,
        label: str,
        tier: str,
        samples: list[float],
        load_ms: float,
        detections: int,
        preprocess_ms: float | None = None,
        postprocess_ms: float | None = None,
        was_loaded: bool = False,
        released: bool = False,
    ) -> BenchmarkEntry:
        """Construit une ligne réussie à partir de la série de mesures retenues.

        La série reçue ici a **déjà** perdu son run de chauffe : ce constructeur
        ne connaît pas cette règle, et c'est voulu — le protocole de mesure vit
        dans le service, la statistique vit ici.
        """
        return cls(
            model_id=model_id,
            label=label,
            tier=tier,
            load_ms=load_ms,
            median_ms=median(samples),
            p95_ms=percentile(samples, 0.95),
            min_ms=min(samples) if samples else 0.0,
            max_ms=max(samples) if samples else 0.0,
            preprocess_ms=preprocess_ms,
            postprocess_ms=postprocess_ms,
            detections=detections,
            frames=len(samples),
            was_loaded=was_loaded,
            released=released,
        )

    @classmethod
    def failure(
        cls, *, model_id: str, label: str, tier: str, error: str, released: bool = False
    ) -> BenchmarkEntry:
        """Construit une ligne en échec.

        Elle existe dans le tableau, avec des durées à zéro et son message : un
        modèle absent du résultat serait indistinguable d'un modèle non demandé.
        """
        return cls(model_id=model_id, label=label, tier=tier, error=error, released=released)


@dataclass(slots=True)
class BenchmarkRun:
    """Un run complet, avec le contexte matériel qui lui donne un sens.

    Mutable : il se remplit modèle par modèle, et chaque ligne ajoutée est
    publiée en SSE. Le contexte (`device`, `half`, `ultralytics_version`,
    `image_hash`) est capturé **au démarrage** : un résultat sans son contexte
    matériel est trompeur — 40 ms sur GPU et 40 ms sur CPU ne racontent pas la
    même histoire, et comparer deux runs pris sur des images différentes ne
    compare rien du tout.
    """

    id: str
    status: BenchmarkStatus
    model_ids: tuple[str, ...]
    frames: int
    image_source: ImageSource
    image_hash: str
    image_width: int
    image_height: int
    device: str
    half: bool
    ultralytics_version: str
    confidence_threshold: float
    iou_threshold: float
    job_id: str | None = None
    entries: list[BenchmarkEntry] = field(default_factory=list)
    error: str | None = None

    @property
    def progress(self) -> float:
        """Fraction des modèles mesurés, bornée à 1.

        Bornée par prudence, comme la progression d'un job : une barre à 103 %
        est un bug que tout le monde voit.
        """
        if not self.model_ids:
            return 0.0
        return min(1.0, len(self.entries) / len(self.model_ids))

    @property
    def completed(self) -> int:
        return len(self.entries)

    @property
    def total(self) -> int:
        return len(self.model_ids)

    def fastest(self) -> BenchmarkEntry | None:
        """La ligne réussie la plus rapide, ou `None` si aucune n'a abouti.

        Les lignes en échec sont exclues : leur `median_ms` vaut zéro, et un zéro
        gagnerait tous les classements.
        """
        succeeded = [entry for entry in self.entries if not entry.failed]
        if not succeeded:
            return None
        return min(succeeded, key=lambda entry: entry.median_ms)
