/**
 * Ce que la barre du studio ne peut pas porter d'une analyse en cours.
 *
 * Ce bloc a porté toute la progression : le pourcentage, le compteur d'images, la
 * barre, et les trois boutons Suspendre / Reprendre / Annuler. **Tout cela vit
 * désormais dans la barre du studio**, où on le voit en permanence — ici, il fallait
 * remonter la page pour savoir où en était l'analyse, et le bloc n'apparaissait qu'une
 * fois le job parti.
 *
 * Il reste pour les **cinq choses qui ne tiennent pas dans une pilule**, et qui sont
 * toutes des phrases :
 *
 * - **l'envoi**, avec ses octets. Sur une vidéo de 800 Mo, c'est la seule information
 *   qui dit que quelque chose avance ;
 * - **la file d'attente**, avec la cause de l'attente. Elle a d'abord été rangée avec
 *   « en cours », donc masquée ici : l'écran ne montrait plus qu'un anneau à 0 %, et
 *   le lancement passait pour un échec ;
 * - **la préparation**, avec le nom du modèle qui se charge. Sans elle, l'écran
 *   affichait « 0 / 0 images » pendant une à deux minutes, ce qui se lit exactement
 *   comme une analyse plantée ;
 * - **l'échec**, avec son message — qui vient du serveur et peut faire deux lignes ;
 * - **ce qu'une pause coûte** : un job suspendu garde sa place de calcul et le bail de
 *   son modèle. Sans cette phrase, personne ne comprendrait pourquoi une autre analyse
 *   n'avance pas pendant ce temps.
 *
 * **Il ne calcule plus rien.** La phase, le pourcentage et les phrases viennent de
 * `analysisProgress`, la même fonction que lit la barre : deux calculs du même job
 * finiraient par afficher deux états différents sur le même écran.
 *
 * La barre de progression **reste** ici, et ce n'est pas un doublon de l'anneau : elle
 * ne s'affiche que pendant l'envoi, la seule phase où l'anneau de la barre du studio
 * n'existe pas encore — il n'y a pas encore de job.
 */

import type { Job } from "@/shared/api/contracts";

import type { AnalysisProgress } from "../model/analysisProgress";

interface JobProgressBarProps {
  progress: AnalysisProgress;
  /** Le job, pour son seul message d'erreur : tout le reste passe par `progress`. */
  job: Job | null;
}

export function JobProgressBar({ progress, job }: JobProgressBarProps) {
  const failed = job?.error != null;

  // Une analyse qui tourne normalement n'a plus rien à dire ici : son pourcentage et
  // son compteur d'images sont dans la barre, sous les yeux.
  if (!failed && (progress.phase === "idle" || progress.phase === "running")) return null;

  const uploading = progress.phase === "upload";

  return (
    <div className="rounded-card bg-surface-2 p-3">
      <div className="flex items-baseline justify-between gap-3">
        <p className="text-caption font-bold text-ink">{progress.label}</p>
        {uploading && (
          <output className="text-small text-ink-muted tabular">
            {Math.round(progress.ratio * 100)} %
          </output>
        )}
      </div>

      {/* Seulement pendant l'envoi : l'anneau de la barre prend le relais dès qu'un
          job existe, et deux barres du même pourcentage se contrediraient au premier
          arrondi. */}
      {uploading && (
        <div
          role="progressbar"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={Math.round(progress.ratio * 100)}
          aria-label="Envoi de la vidéo"
          className="mt-2 h-1 overflow-hidden rounded-pill bg-line"
        >
          <div
            className="h-full rounded-pill bg-accent transition-[width] duration-200"
            style={{ width: `${Math.min(100, progress.ratio * 100)}%` }}
          />
        </div>
      )}

      {progress.detail !== null && uploading && (
        <p className="mt-2 text-small text-ink-dim">{progress.detail}</p>
      )}

      {progress.hint !== null && <p className="mt-2 text-small text-ink-dim">{progress.hint}</p>}

      {job?.error != null && (
        <p role="alert" className="mt-2 text-small text-negative">
          {job.error}
        </p>
      )}
    </div>
  );
}
