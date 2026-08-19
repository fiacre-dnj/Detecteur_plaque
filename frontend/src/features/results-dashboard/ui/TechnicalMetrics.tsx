/**
 * Les trois chiffres **de machine**, posés à l'extrémité de la barre du studio.
 *
 * Cadence serveur, latence par image, durée de vidéo déjà traitée : ils disent
 * comment l'analyse se passe, jamais ce qu'elle a trouvé. Ils occupaient trois des
 * cinq cartes de tête de la colonne de résultats, au même poids visuel que
 * « Entrées au carrefour » — donc la moitié de l'espace le mieux placé de l'écran
 * pour de la métrologie qu'on surveille du coin de l'œil.
 *
 * **Volontairement sobre** : une rangée de libellé-plus-chiffre, séparateurs fins,
 * aucune carte, aucune ombre. Une `MetricCard` ici les remettrait au niveau des
 * chiffres du carrefour, ce qui est exactement ce qu'on vient de défaire.
 *
 * Les libellés gardent leur précision d'origine, qui n'est pas cosmétique :
 * « Cadence serveur » et non « Cadence » — la cadence de **lecture** de la vidéo
 * est un autre chiffre, affiché sur la scène (`PlaybackFpsBadge`), et l'écart
 * entre les deux est justement ce qui explique une relecture saccadée. Le détail
 * complet vit dans l'attribut `title`, faute de place pour une phrase.
 */

import type { AnalysisStats } from "@/shared/api/contracts";

import { formatFrameLatency, formatSceneTime } from "../model/labels";

interface TechnicalMetricsProps {
  /** Cadence de traitement du **serveur**, distincte de la lecture vidéo. */
  processingFps: number;
  stats: AnalysisStats;
}

export function TechnicalMetrics({ processingFps, stats }: TechnicalMetricsProps) {
  return (
    <dl className="flex items-center gap-3">
      <Metric
        label="Cadence serveur"
        value={processingFps > 0 ? processingFps.toFixed(1) : "—"}
        unit="img/s"
        hint="Images analysées par seconde par le serveur — pas la cadence de lecture de la vidéo"
      />
      <Metric
        label="Latence"
        value={formatFrameLatency(processingFps)}
        // Dit ce que le chiffre mesure : le traitement d'une image côté serveur,
        // et non un aller-retour réseau — en différé, il n'y en a pas par image.
        hint="Temps de traitement d'une image côté serveur"
      />
      <Metric
        label="Flux analysé"
        value={formatSceneTime(stats.analysedSceneMs)}
        // Temps de **scène**, pas temps mural : c'est la durée de vidéo déjà
        // traitée, pas le temps que le serveur a mis pour la traiter.
        hint="Durée de vidéo déjà traitée par le serveur"
      />
    </dl>
  );
}

/**
 * Un chiffre et son libellé, empilés.
 *
 * Le séparateur est porté par l'élément lui-même (`border-s`, retiré du premier
 * par `first:border-0`) plutôt que par des `<div>` intercalés : un séparateur qui
 * n'est pas du contenu n'a rien à faire dans une liste de définitions, où un
 * lecteur d'écran l'annoncerait comme un terme vide.
 */
function Metric({
  label,
  value,
  unit,
  hint,
}: {
  label: string;
  value: string;
  unit?: string;
  hint: string;
}) {
  return (
    <div className="flex flex-col border-s border-line/60 ps-3 first:border-0 first:ps-0" title={hint}>
      <dt className="label-micro">{label}</dt>
      <dd className="text-caption font-bold leading-tight text-ink tabular">
        {value}
        {unit !== undefined && <span className="ms-1 text-micro font-normal text-ink-dim">{unit}</span>}
      </dd>
    </div>
  );
}
