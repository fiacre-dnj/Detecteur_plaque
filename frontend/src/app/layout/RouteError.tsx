/**
 * Frontière d'erreur d'une route.
 *
 * Le message dit **ce qui a échoué et l'action suivante**, en français, et
 * affiche l'identifiant de requête quand il existe — c'est ce qui rend un
 * rapport d'incident exploitable. Jamais de trace de pile, jamais un statut nu.
 */

import { useRouteError } from "react-router";

import { ApiError } from "@/shared/api/httpClient";
import { Button } from "@/shared/ui/Button";

export function RouteError() {
  const error = useRouteError();
  const apiError = error instanceof ApiError ? error : null;

  return (
    <section className="mx-auto max-w-lg rounded-section bg-surface p-8 text-center shadow-card">
      <h2 className="text-heading font-bold text-ink">Cet écran n'a pas pu s'afficher</h2>
      <p className="mt-2 text-caption text-ink-muted">
        {apiError?.message ?? "Une erreur inattendue est survenue."}
      </p>
      {apiError?.requestId ? (
        <p className="mt-3 text-small text-ink-dim">
          Identifiant à citer si vous signalez le problème :{" "}
          <code className="text-ink-muted">{apiError.requestId}</code>
        </p>
      ) : null}
      <div className="mt-6 flex justify-center gap-3">
        <Button variant="primary" onClick={() => window.location.reload()}>
          Recharger
        </Button>
        <Button variant="ghost" onClick={() => window.history.back()}>
          Revenir
        </Button>
      </div>
    </section>
  );
}
