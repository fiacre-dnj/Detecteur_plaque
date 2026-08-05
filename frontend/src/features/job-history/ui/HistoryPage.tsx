/**
 * L'historique des analyses persistées.
 *
 * Trois actions, et la nuance qui compte : **« Relancer » crée un nouveau job**,
 * jamais une mutation de l'ancien. Un job muté perdrait ses chiffres d'origine, et on
 * ne pourrait plus comparer « avant » et « après » un changement de réglage. La
 * relance recharge donc la configuration dans le studio, et l'utilisateur redéposera
 * la vidéo — le serveur ne l'a plus, son TTL étant plus court que celui du job.
 *
 * C'est aussi pourquoi « Ouvrir » et « Relancer » mènent au même écran : la seule
 * différence est ce qui est prérempli.
 */

import { RotateCcw, Trash2 } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router";

import { useModels } from "@/entities/model";
import type { JobStatus } from "@/shared/api/contracts";
import { Button } from "@/shared/ui/Button";

import {
  NO_FILTERS,
  PAGE_SIZE,
  durationSeconds,
  formatDateTime,
  statusTone,
  useDeleteJob,
  useJobConfig,
  useJobHistory,
  type HistoryFilters,
} from "../model/useJobHistory";

const STATUSES: readonly JobStatus[] = ["queued", "running", "done", "error", "cancelled"];

export function HistoryPage() {
  const [filters, setFilters] = useState<HistoryFilters>(NO_FILTERS);
  const [offset, setOffset] = useState(0);
  const { data, isLoading, error } = useJobHistory(filters, offset);
  const { data: catalogue } = useModels();
  const remove = useDeleteJob();
  const config = useJobConfig();
  const navigate = useNavigate();

  /**
   * Recharge la configuration puis ouvre le studio.
   *
   * La configuration est passée par l'état de navigation plutôt que par l'URL :
   * une géométrie complète dans une query string dépasserait vite la longueur
   * acceptée et serait illisible dans la barre d'adresse.
   */
  const openInStudio = async (jobId: string, replay: boolean): Promise<void> => {
    const loaded = await config.load(jobId);
    if (loaded === null) return;
    void navigate("/", { state: { jobId, config: loaded, replay } });
  };

  if (isLoading) {
    // Squelette de la forme finale plutôt qu'un spinner : l'utilisateur voit
    // arriver un tableau, pas une roue qui tourne.
    return (
      <div className="space-y-2">
        <div className="h-10 rounded-card bg-surface" />
        <div className="h-64 rounded-section bg-surface" />
      </div>
    );
  }

  if (error !== null) {
    return (
      <section role="alert" className="rounded-section bg-surface p-6 shadow-card">
        <h2 className="text-heading font-bold text-ink">L'historique n'a pas pu être chargé</h2>
        <p className="mt-2 text-caption text-ink-muted">
          {error instanceof Error ? error.message : "Le serveur ne répond pas."}
        </p>
      </section>
    );
  }

  const jobs = data?.items ?? [];
  const total = data?.total ?? 0;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end gap-3">
        <label className="flex flex-col gap-1 text-small text-ink-muted">
          Statut
          <select
            value={filters.status ?? ""}
            onChange={(event) => {
              setOffset(0);
              setFilters((previous) => ({
                ...previous,
                status: (event.target.value || null) as JobStatus | null,
              }));
            }}
            className="rounded-input bg-elevated px-2 py-1 text-small text-ink"
          >
            <option value="">tous</option>
            {STATUSES.map((status) => (
              <option key={status} value={status}>
                {statusTone(status).label}
              </option>
            ))}
          </select>
        </label>

        <label className="flex flex-col gap-1 text-small text-ink-muted">
          Modèle
          <select
            value={filters.modelId ?? ""}
            onChange={(event) => {
              setOffset(0);
              setFilters((previous) => ({ ...previous, modelId: event.target.value || null }));
            }}
            className="rounded-input bg-elevated px-2 py-1 text-small text-ink"
          >
            <option value="">tous</option>
            {(catalogue?.models ?? []).map((model) => (
              <option key={model.id} value={model.id}>
                {model.label}
              </option>
            ))}
          </select>
        </label>

        <p className="ms-auto text-small text-ink-dim tabular">
          {total} analyse{total === 1 ? "" : "s"}
        </p>
      </div>

      {config.error !== null && (
        <p role="alert" className="text-small text-negative">
          {config.error}
        </p>
      )}

      {jobs.length === 0 ? (
        <section className="rounded-section bg-surface p-8 text-center shadow-card">
          <h2 className="text-heading font-bold text-ink">
            {filters.status === null && filters.modelId === null
              ? "Aucune analyse pour l'instant"
              : "Aucune analyse ne correspond à ces filtres"}
          </h2>
          <p className="mx-auto mt-2 max-w-md text-caption text-ink-muted">
            {filters.status === null && filters.modelId === null
              ? "Les analyses terminées apparaîtront ici. Vous pourrez les relire sans les relancer, ou les rejouer avec la même configuration."
              : "Élargissez les filtres pour voir les autres analyses."}
          </p>
        </section>
      ) : (
        <div className="overflow-x-auto rounded-card bg-surface shadow-card">
          <table className="w-full border-collapse text-small">
            <thead>
              <tr>
                <Th>Date</Th>
                <Th>Fichier</Th>
                <Th>Modèle</Th>
                <Th>Statut</Th>
                <Th>Durée</Th>
                <Th>Images</Th>
                <Th>Actions</Th>
              </tr>
            </thead>
            <tbody>
              {jobs.map((job) => {
                const tone = statusTone(job.status);
                const seconds = durationSeconds(job);
                return (
                  <tr key={job.jobId} className="border-t border-line/40">
                    <td className="px-3 py-2 text-ink-muted tabular">
                      {formatDateTime(job.createdAt)}
                    </td>
                    <td className="max-w-48 truncate px-3 py-2 text-ink" title={job.fileName}>
                      {job.fileName}
                    </td>
                    <td className="px-3 py-2 text-ink-muted">{job.modelId}</td>
                    <td className={`px-3 py-2 ${tone.className}`}>
                      {tone.label}
                      {job.error !== null && (
                        <span className="block text-micro text-negative">{job.error}</span>
                      )}
                    </td>
                    <td className="px-3 py-2 text-ink-muted tabular">
                      {seconds === null ? "—" : `${seconds} s`}
                    </td>
                    <td className="px-3 py-2 text-ink-muted tabular">
                      {job.processedFrames} / {job.totalFrames}
                    </td>
                    <td className="px-3 py-2">
                      <span className="flex gap-1">
                        <Button
                          size="sm"
                          variant="ghost"
                          disabled={job.status !== "done" || config.loading}
                          title={
                            job.status === "done"
                              ? "Recharge le résultat et sa géométrie dans le studio"
                              : "Seule une analyse terminée peut être ouverte"
                          }
                          onClick={() => void openInStudio(job.jobId, true)}
                        >
                          Ouvrir
                        </Button>
                        <Button
                          size="sm"
                          variant="ghost"
                          icon={<RotateCcw className="size-3.5" />}
                          disabled={config.loading}
                          // L'infobulle énonce la règle : jamais une mutation.
                          title="Préremplit le studio avec la même configuration — crée un nouveau job, ne modifie jamais celui-ci"
                          onClick={() => void openInStudio(job.jobId, false)}
                        >
                          Relancer
                        </Button>
                        <Button
                          size="sm"
                          variant="danger"
                          icon={<Trash2 className="size-3.5" />}
                          disabled={remove.isPending}
                          title="Supprime le job et son résultat, définitivement"
                          onClick={() => remove.mutate(job.jobId)}
                        >
                          Supprimer
                        </Button>
                      </span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {total > PAGE_SIZE && (
        <div className="flex items-center justify-between">
          <Button
            size="sm"
            variant="ghost"
            disabled={offset === 0}
            onClick={() => setOffset((value) => Math.max(0, value - PAGE_SIZE))}
          >
            Précédentes
          </Button>
          <p className="text-small text-ink-dim tabular">
            {offset + 1}–{Math.min(offset + PAGE_SIZE, total)} sur {total}
          </p>
          <Button
            size="sm"
            variant="ghost"
            disabled={offset + PAGE_SIZE >= total}
            onClick={() => setOffset((value) => value + PAGE_SIZE)}
          >
            Suivantes
          </Button>
        </div>
      )}
    </div>
  );
}

function Th({ children }: { children: React.ReactNode }) {
  return (
    <th
      scope="col"
      className="px-3 py-2 text-start text-micro font-semibold uppercase tracking-wider text-ink-dim"
    >
      {children}
    </th>
  );
}

export default HistoryPage;
