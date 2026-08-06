"""Le protocole du WebSocket temps réel, et les codes de fermeture.

Le protocole est **strictement séquencé** : `init` → `ready` → (`frame` texte +
JPEG binaire) → `frameResult`. Cette rigidité est délibérée — un protocole où
l'ordre est libre demanderait un état côté serveur pour savoir ce qu'il attend, et
c'est exactement là que les bugs de concurrence se logent.

**La règle qui justifie ce module à elle seule : `ready` renvoie les dimensions
réellement reçues.** Le client réduit ses frames à ~960 px pour tenir le débit, et
doit donc mettre sa géométrie à la même échelle avant l'`init`. S'il oublie, une
ligne tracée sur du 1280 px est appliquée à une image de 960 : elle est comptée
**25 % à côté**, et *aucune* erreur n'est levée — le serveur compte
consciencieusement au mauvais endroit. C'est le pire mode de défaillance possible,
parce qu'il est silencieux et que les chiffres restent plausibles. Le serveur se
protège en disant ce qu'il a reçu ; le client compare et refuse s'il y a un écart.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from traffic_analysis.core.schemas import CamelModel
from traffic_analysis.features.counting.application.request_schema import AnalysisRequestSchema

# ── Codes de fermeture ───────────────────────────────────────────────────────
#
# Les codes de la RFC 6455 ont un sens précis, et les confondre prive le client de
# toute possibilité de réagir correctement.

#: Violation de politique — init invalide, ou origine refusée. Le client ne doit
#: **pas** réessayer : sa requête est fautive, pas le serveur.
CLOSE_POLICY_VIOLATION = 1008

#: Erreur interne. Le client peut réessayer plus tard.
CLOSE_INTERNAL_ERROR = 1011

#: « Try again later » — une session est déjà active. Le client peut réessayer,
#: et c'est justement ce qui distingue ce cas du 1008.
CLOSE_TRY_AGAIN_LATER = 1013

#: Longueur maximale d'une raison de fermeture. La RFC 6455 borne le corps du
#: message de fermeture à 125 octets, dont 2 pour le code : une raison plus longue
#: fait échouer la fermeture elle-même, et le client reçoit une coupure brutale au
#: lieu de son explication.
MAX_CLOSE_REASON_BYTES = 123


def truncate_reason(reason: str) -> str:
    """Tronque une raison de fermeture pour tenir dans la trame de la RFC 6455.

    Sur les **octets** et non les caractères : un message français est plein
    d'accents, qui pèsent deux octets en UTF-8. Compter les caractères laisserait
    passer une raison de 123 caractères et 140 octets, et la fermeture échouerait.
    """
    encoded = reason.encode("utf-8")
    if len(encoded) <= MAX_CLOSE_REASON_BYTES:
        return reason
    # `errors="ignore"` recoupe proprement un caractère multi-octets tranché en
    # deux par la troncature.
    return encoded[:MAX_CLOSE_REASON_BYTES].decode("utf-8", errors="ignore")


# ── Messages client → serveur ────────────────────────────────────────────────


class InitMessage(CamelModel):
    """Premier message de la session : la configuration de l'analyse.

    Réutilise `AnalysisRequestSchema` **entièrement** : les seuils, la géométrie et
    les règles de comptage sont les mêmes qu'en différé, et c'est ce qui garantit
    qu'un même tracé donne les mêmes chiffres dans les deux modes. Un schéma
    parallèle finirait par divulguer une différence de validation.
    """

    type: Literal["init"]
    request: AnalysisRequestSchema


class FrameMessage(CamelModel):
    """Annonce d'une frame. **Suivie immédiatement** du JPEG en binaire.

    Deux messages plutôt qu'un JPEG avec en-tête : le binaire reste brut, donc
    décodable sans découpage manuel, et l'horodatage reste lisible dans les
    journaux.
    """

    type: Literal["frame"]
    #: Temps de **scène** décidé par le client, pas l'horloge du serveur : c'est
    #: lui qui sait à quel instant de son flux la frame appartient (invariant 1).
    timestamp_ms: float = Field(ge=0)


# ── Messages serveur → client ────────────────────────────────────────────────


class ReadyMessage(CamelModel):
    """Réponse à l'`init` — **le filet contre une géométrie mal mise à l'échelle**.

    `frameWidth` et `frameHeight` sont `null` jusqu'à la première frame : le serveur
    ne peut pas les connaître avant d'avoir reçu une image, et les inventer serait
    exactement le mensonge que ce message existe pour empêcher. Ils sont renvoyés à
    nouveau dans le premier `frameResult`.
    """

    type: Literal["ready"] = "ready"
    #: Dimensions **réellement reçues**, à comparer avec ce que le client croit
    #: envoyer. Un écart signifie une géométrie à la mauvaise échelle.
    frame_width: int | None = None
    frame_height: int | None = None
    #: Modèle effectivement utilisé, et device : le client les affiche, et ils
    #: peuvent différer de ce qui a été demandé si le serveur a dû se replier.
    model_id: str
    device: str


class FrameResultMessage(CamelModel):
    """Résultat d'une frame.

    Les champs `tracks`, `crossings`, `zoneEvents` et `stats` portent **exactement**
    la même forme que dans le résultat différé : ils sortent des mêmes sérialiseurs.
    Le client réutilise donc son code d'affichage sans branche conditionnelle.
    """

    type: Literal["frameResult"] = "frameResult"
    timestamp_ms: float
    frame_index: int
    #: Répétées à chaque frame : coûteux en octets ? Deux entiers. Utile ? Le client
    #: peut détecter un changement de résolution en cours de session — ce qui arrive
    #: quand une webcam renégocie son flux.
    frame_width: int
    frame_height: int
    tracks: list[dict[str, Any]]
    crossings: list[dict[str, Any]]
    zone_events: list[dict[str, Any]]
    stats: dict[str, Any]


class ErrorMessage(CamelModel):
    """Erreur non fatale : la session continue.

    Distincte d'une fermeture 1011. Une frame illisible — JPEG tronqué par un
    réseau capricieux — ne doit pas tuer la session : le client en enverra une autre
    dans 30 millisecondes. Fermer serait une réaction disproportionnée qui
    obligerait à tout reconstruire.
    """

    type: Literal["error"] = "error"
    detail: str
    code: str
