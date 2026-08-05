"""La route WebSocket du comptage en direct.

**L'ordre des opérations avant `accept()` est le contrat de sécurité et de
ressource** :

1. vérifier l'`Origin` — un WebSocket n'est pas protégé par la politique de même
   origine, et le `CORSMiddleware` ne voit jamais passer un handshake ;
2. réserver une place de session — refuser en **1013** sans avoir ouvert la
   connexion ;
3. *puis* `accept()`.

Accepter d'abord et fermer ensuite serait fonctionnellement proche mais laisserait
chaque connexion refusée aboutir jusqu'au handshake complet, ce qui suffit à sonder
le service et consomme un descripteur de fichier par tentative.

Après l'`accept()`, la boucle est simple parce que le protocole est séquencé :
`frame` texte puis JPEG binaire, sans exception. Le `finally` ferme le flux et
**rend le bail du modèle** — un bail non rendu immobilise une instance jusqu'au
redémarrage du service, et rien à l'écran ne l'explique.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import ValidationError
from starlette.websockets import WebSocketState

from traffic_analysis.core.logging import get_logger
from traffic_analysis.features.realtime.api.origin_check import (
    is_origin_allowed,
    rejection_reason,
)
from traffic_analysis.features.realtime.api.protocol import (
    CLOSE_INTERNAL_ERROR,
    CLOSE_POLICY_VIOLATION,
    CLOSE_TRY_AGAIN_LATER,
    ErrorMessage,
    FrameMessage,
    InitMessage,
    ReadyMessage,
    truncate_reason,
)
from traffic_analysis.features.realtime.infrastructure.jpeg_decoder import decode_jpeg

if TYPE_CHECKING:
    from traffic_analysis.container import Container
    from traffic_analysis.features.counting.application.dto import AnalysisJobConfig
    from traffic_analysis.features.realtime.application.session_service import LiveSession

logger = get_logger("traffic_analysis.realtime")

router = APIRouter(tags=["realtime"])


@router.websocket("/realtime")
async def realtime(websocket: WebSocket) -> None:
    """Comptage en direct sur un flux de frames JPEG.

    Documenté à la main dans OpenAPI (`core/openapi.py`) : FastAPI ne génère pas de
    schéma pour les WebSockets, et le protocole a besoin d'être décrit quelque part
    que le client puisse lire.
    """
    container = websocket.app.state.container
    settings = container.settings
    service = container.realtime_service

    # ── 1. Origine, **avant tout** ───────────────────────────────────────────
    origin = websocket.headers.get("origin")
    if not is_origin_allowed(origin, settings.cors_origins):
        logger.warning("handshake temps réel refusé", origin=origin)
        # `close()` sans `accept()` : le handshake est refusé au niveau HTTP, la
        # connexion WebSocket n'existe jamais.
        await websocket.close(
            code=CLOSE_POLICY_VIOLATION, reason=truncate_reason(rejection_reason(origin))
        )
        return

    # ── 2. Place de session, toujours avant `accept()` ───────────────────────
    if service is None or not service.try_acquire():
        await websocket.close(
            code=CLOSE_TRY_AGAIN_LATER,
            reason=truncate_reason(
                "Une session temps réel est déjà active sur ce serveur. Réessayez dans un instant."
            ),
        )
        return

    # ── 3. Seulement maintenant ──────────────────────────────────────────────
    await websocket.accept()

    session = None
    try:
        config = await _read_init(websocket)
        if config is None:
            return  # `_read_init` a déjà fermé avec sa raison.

        session = service.open(config)
        await websocket.send_json(
            ReadyMessage(
                model_id=config.model_id,
                device=_device_of(container),
            ).model_dump(by_alias=True)
        )

        await _pump_frames(websocket, session)

    except WebSocketDisconnect:
        # Le client est parti. Ce n'est pas une erreur : c'est la fin normale d'une
        # session temps réel, où personne n'envoie de message d'adieu.
        logger.info("session temps réel fermée par le client")
    except Exception as exc:
        logger.exception("session temps réel en échec", exc_info=exc)
        await _close_quietly(
            websocket,
            CLOSE_INTERNAL_ERROR,
            "Une erreur interne a interrompu la session. Consultez les journaux du serveur.",
        )
    finally:
        # **Les deux libérations, dans cet ordre.** Le flux rend le bail du modèle ;
        # la place de session autorise la connexion suivante. Oublier l'une des deux
        # bloque le service jusqu'au redémarrage.
        if session is not None:
            session.close()
        service.release()


async def _read_init(websocket: WebSocket) -> AnalysisJobConfig | None:
    """Lit et valide le message `init`. Ferme en 1008 et rend `None` s'il est fautif.

    La validation réutilise `AnalysisRequestSchema` : mêmes bornes, mêmes refus, même
    message d'erreur qu'en différé. Un schéma parallèle finirait par divulguer une
    différence de validation entre les deux modes, et le même tracé ne compterait
    plus pareil.
    """
    raw = await websocket.receive_text()
    try:
        message = InitMessage.model_validate_json(raw)
    except ValidationError as exc:
        # Le premier message d'erreur suffit et **dit quel champ** : renvoyer la
        # liste complète de pydantic dans 123 octets est impossible de toute façon.
        detail = _first_error(exc)
        logger.info("init temps réel invalide", detail=detail)
        await _close_quietly(websocket, CLOSE_POLICY_VIOLATION, f"Init invalide : {detail}")
        return None

    return message.request.to_config()


async def _pump_frames(websocket: WebSocket, session: LiveSession) -> None:
    """Boucle principale : `frame` texte, puis JPEG binaire, puis `frameResult`.

    Une frame illisible produit un message `error` **sans fermer** : un JPEG tronqué
    par un réseau capricieux est un incident normal, et le client en enverra un autre
    dans 30 millisecondes. Fermer obligerait à tout reconstruire pour rien.
    """
    while True:
        announcement = await websocket.receive_text()
        try:
            frame = FrameMessage.model_validate_json(announcement)
        except ValidationError as exc:
            await websocket.send_json(
                ErrorMessage(detail=_first_error(exc), code="invalid_frame_header").model_dump(
                    by_alias=True
                )
            )
            continue

        payload = await websocket.receive_bytes()
        image = decode_jpeg(payload)
        if image is None:
            await websocket.send_json(
                ErrorMessage(
                    detail="Cette image n'a pas pu être décodée. Elle est ignorée.",
                    code="undecodable_frame",
                ).model_dump(by_alias=True)
            )
            continue

        result = await session.process(image, frame.timestamp_ms)
        await websocket.send_json({"type": "frameResult", **result})


def _device_of(container: Container) -> str:
    """Device du serveur, ou « inconnu ».

    Une chaîne et jamais une exception : le message `ready` ne doit pas faire échouer
    une session parce que le registre n'est pas configuré.
    """
    registry = getattr(container, "model_registry", None)
    if registry is None:
        return "inconnu"
    try:
        device: str = registry.device()
    except Exception:  # pragma: no cover — garde-fou
        return "inconnu"
    return device


def _first_error(exc: ValidationError) -> str:
    """Première erreur de validation, sous forme « champ : message »."""
    errors = exc.errors()
    if not errors:  # pragma: no cover — pydantic en rend toujours au moins une
        return "message mal formé"
    first = errors[0]
    location = ".".join(str(part) for part in first.get("loc", ()) if part != "request")
    message = str(first.get("msg", "valeur refusée"))
    return f"{location} : {message}" if location else message


async def _close_quietly(websocket: WebSocket, code: int, reason: str) -> None:
    """Ferme sans lever si la connexion est déjà partie.

    Le cas arrive vraiment : le client peut fermer pendant qu'on prépare notre propre
    fermeture, et un `close()` sur une socket morte lève. Laisser cette exception
    remonter masquerait la cause réelle dans les journaux.
    """
    if websocket.client_state is WebSocketState.DISCONNECTED:
        return
    try:
        await websocket.close(code=code, reason=truncate_reason(reason))
    except Exception:  # pragma: no cover — socket déjà fermée
        logger.debug("fermeture sur une connexion déjà close")
