"""Hiérarchie d'erreurs applicatives et traduction en Problem Details (RFC 9457).

Le domaine et l'application lèvent des `AppError`. Elles ne connaissent pas
HTTP : lever une `HTTPException` depuis une couche métier couple la logique au
transport et rend le domaine intestable hors FastAPI. La traduction se fait
**une seule fois**, dans un gestionnaire d'exceptions.
"""

from __future__ import annotations


class AppError(Exception):
    """Erreur applicative traduisible en réponse HTTP.

    `code` est stable et destiné aux machines (le frontend branche dessus) ;
    `detail` est un message français destiné aux humains. Les deux existent
    parce qu'un message d'interface change sans casser un client.
    """

    status_code: int = 500
    code: str = "internal_error"

    def __init__(self, detail: str, *, code: str | None = None) -> None:
        super().__init__(detail)
        self.detail = detail
        if code is not None:
            self.code = code

    def __str__(self) -> str:
        return self.detail


class NotFoundError(AppError):
    status_code = 404
    code = "not_found"


class ConflictError(AppError):
    status_code = 409
    code = "conflict"


class ValidationAppError(AppError):
    status_code = 422
    code = "validation_error"


class PayloadTooLargeError(AppError):
    status_code = 413
    code = "payload_too_large"


class UnsupportedMediaError(AppError):
    status_code = 415
    code = "unsupported_media_type"


class UnavailableError(AppError):
    status_code = 503
    code = "unavailable"


class UnknownModelError(NotFoundError):
    code = "unknown_model"


class JobNotFoundError(NotFoundError):
    code = "job_not_found"


# Titres français par code de statut. Ils servent le champ `title` de
# Problem Details, que la RFC veut stable pour un type d'erreur donné — donc
# dérivé du statut, jamais du message particulier de l'occurrence.
STATUS_TITLES: dict[int, str] = {
    400: "Requête invalide",
    404: "Ressource introuvable",
    409: "Conflit avec l'état courant",
    413: "Contenu trop volumineux",
    415: "Type de média non supporté",
    422: "Requête non traitable",
    429: "Trop de requêtes",
    500: "Erreur interne du service",
    503: "Service indisponible",
}

DEFAULT_TITLE = "Erreur"


def title_for(status_code: int) -> str:
    return STATUS_TITLES.get(status_code, DEFAULT_TITLE)


# Starlette et FastAPI lèvent leurs propres `HTTPException` avec un `detail`
# anglais issu de la phrase HTTP (« Not Found », « Method Not Allowed »).
# Toute la copie destinée à l'utilisateur est en français : ces messages sont
# donc remplacés, et ils disent en plus **quoi faire ensuite** — un statut nu ne
# renseigne personne.
FRAMEWORK_DETAILS: dict[int, str] = {
    400: "La requête est mal formée.",
    404: "Cette ressource n'existe pas. Vérifiez le chemin appelé.",
    405: "Cette méthode HTTP n'est pas acceptée sur ce chemin.",
    406: "Aucun des formats de réponse demandés n'est disponible.",
    413: "Le contenu envoyé dépasse la taille maximale acceptée.",
    415: "Le type de média envoyé n'est pas supporté.",
    429: "Trop de requêtes. Réessayez après le délai indiqué par « Retry-After ».",
    500: "Une erreur interne est survenue.",
    503: "Le service est momentanément indisponible.",
}


def detail_for_framework_error(status_code: int, original: str) -> str:
    """Traduit un `detail` générique du framework, préserve un message explicite.

    Un `detail` posé volontairement par une route (« Le job est encore en cours »)
    doit survivre ; seule la phrase HTTP anglaise par défaut est remplacée. Le
    critère est la correspondance avec cette phrase, ce qui évite d'écraser un
    message utile.
    """
    from http import HTTPStatus

    try:
        default_phrase = HTTPStatus(status_code).phrase
    except ValueError:
        return original
    if original.strip().casefold() != default_phrase.casefold():
        return original
    return FRAMEWORK_DETAILS.get(status_code, f"La requête a échoué ({status_code}).")
