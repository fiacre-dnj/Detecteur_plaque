/**
 * L'URL du WebSocket, et la traduction des codes de fermeture en messages.
 *
 * Deux fonctions pures, séparées du hook pour être testables : construire une URL
 * `wss:` depuis une page `https:` et interpréter un code RFC 6455 sont exactement le
 * genre de détail qu'on écrit une fois de travers et qui ne se voit qu'en production.
 */

/** Chemin du WebSocket temps réel — le même préfixe `/api/v1` que le reste. */
export const REALTIME_PATH = "/api/v1/realtime";

/**
 * URL absolue du WebSocket depuis l'origine courante.
 *
 * **Le schéma suit celui de la page**, et c'est obligatoire : un navigateur refuse
 * un `ws:` non chiffré depuis une page `https:` (contenu mixte). Coder `ws:` en dur
 * marcherait parfaitement en développement sur `http://localhost` et échouerait au
 * premier déploiement derrière TLS, avec une erreur de sécurité que personne ne
 * relie au code.
 *
 * L'origine plutôt qu'un hôte configuré : le proxy de développement de Vite renvoie
 * `/api` vers le backend, donc la même URL relative marche des deux côtés. Un hôte
 * dans une variable d'environnement serait une chose de plus à garder d'accord.
 */
export function realtimeUrl(location: { protocol: string; host: string }): string {
  const scheme = location.protocol === "https:" ? "wss:" : "ws:";
  return `${scheme}//${location.host}${REALTIME_PATH}`;
}

/* ── Codes de fermeture, miroir de `realtime/api/protocol.py` ──────────────── */

/** Init invalide, ou origine refusée. **Ne pas réessayer** : la requête est fautive. */
export const CLOSE_POLICY_VIOLATION = 1008;
/** Erreur interne du serveur. Réessayer plus tard est légitime. */
export const CLOSE_INTERNAL_ERROR = 1011;
/** Une session est déjà active. C'est ce qui distingue ce cas du 1008. */
export const CLOSE_TRY_AGAIN_LATER = 1013;

export interface CloseVerdict {
  message: string;
  /** L'utilisateur peut-il utilement réessayer ? Décide de la présence du bouton. */
  retryable: boolean;
}

/**
 * Traduit une fermeture en message français, et dit si réessayer a un sens.
 *
 * `retryable` n'est pas cosmétique : proposer « Réessayer » après un 1008 enverrait
 * l'utilisateur dans une boucle d'échecs identiques, puisque c'est sa requête qui
 * est refusée. Après un 1013, au contraire, réessayer est **la** bonne action.
 *
 * La raison du serveur est préférée quand elle existe : elle est plus précise que
 * tout ce qu'on peut écrire ici — elle nomme le champ fautif de l'`init`. Le texte
 * générique n'est qu'un repli pour les fermetures sans raison, notamment celles que
 * le navigateur fabrique lui-même quand le réseau tombe.
 */
export function closeVerdict(code: number, reason: string): CloseVerdict {
  const trimmed = reason.trim();

  switch (code) {
    case 1000:
      return { message: "La session en direct est terminée.", retryable: true };
    case CLOSE_POLICY_VIOLATION:
      return {
        message:
          trimmed === ""
            ? "Le serveur a refusé la session : la configuration envoyée est invalide."
            : trimmed,
        // Faux : la même requête sera refusée à l'identique. L'utilisateur doit
        // corriger ses réglages, pas cliquer à nouveau.
        retryable: false,
      };
    case CLOSE_TRY_AGAIN_LATER:
      return {
        message:
          trimmed === ""
            ? "Une session en direct est déjà active sur ce serveur. Réessayez dans un instant."
            : trimmed,
        retryable: true,
      };
    case CLOSE_INTERNAL_ERROR:
      return {
        message:
          trimmed === ""
            ? "Le serveur a interrompu la session sur une erreur interne."
            : trimmed,
        retryable: true,
      };
    default:
      // 1006 arrive ici : « fermeture anormale », fabriqué par le navigateur quand
      // la connexion tombe sans trame de fermeture. Aucune raison n'accompagne
      // jamais ce code — c'est pourquoi le repli générique doit rester utile.
      return {
        message:
          trimmed === ""
            ? "La connexion avec le serveur a été perdue. Le comptage en direct est arrêté."
            : trimmed,
        retryable: true,
      };
  }
}

/**
 * Le message d'un `close` **est-il exploitable** ?
 *
 * Utilitaire minuscule mais il évite une confusion réelle : `event.reason` est la
 * chaîne vide et non `undefined` quand le serveur n'en donne pas, donc un test de
 * nullité passerait et on afficherait un message vide.
 */
export function hasReason(reason: string | null | undefined): boolean {
  return typeof reason === "string" && reason.trim() !== "";
}
