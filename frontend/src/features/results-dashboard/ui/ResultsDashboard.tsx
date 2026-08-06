/**
 * Le tableau de résultats : cartes, répartition, détail par ligne et par zone.
 *
 * Un principe traverse tous ces affichages : **chaque chiffre dit d'où il vient**.
 * « Cadence (serveur) » et non « Cadence », « entrées uniques » et non « entrées »,
 * « ↑ p · ↓ n » avec l'infobulle qui explique la convention A→B. Sans ces
 * précisions, deux chiffres voisins qui ne mesurent pas la même chose se
 * confondent, et l'utilisateur tire une conclusion fausse sans jamais s'en douter.
 */

import type { ReactNode } from "react";

import type { AnalysisStats, CountingLine, Zone } from "@/shared/api/contracts";
import { MetricCard } from "@/shared/ui/MetricCard";

import { VEHICLE_CLASSES, classLabel, formatSceneTime } from "../model/labels";

interface ResultsDashboardProps {
  stats: AnalysisStats;
  lines: readonly CountingLine[];
  zones: readonly Zone[];
  /** Cadence de traitement du **serveur**, distincte de la lecture vidéo. */
  processingFps: number;
  /** Vrai en relecture : l'occupation de zone n'est alors pas calculable. */
  replaying: boolean;
  /**
   * Contenu inséré **entre la répartition par type et le détail par ligne**.
   *
   * Un emplacement et non une place libre en bas : ce qui vient s'y loger — le
   * journal des franchissements pendant une analyse — se lit juste après les
   * totaux qu'il détaille, et juste avant le détail par ligne qui les répartit.
   * Le tableau de bord ignore ce qu'on lui passe ; c'est le Studio qui décide,
   * comme pour tout le reste du câblage entre features.
   */
  children?: ReactNode;
}

export function ResultsDashboard({
  stats,
  lines,
  zones,
  processingFps,
  replaying,
  children,
}: ResultsDashboardProps) {
  const rateAvailable = stats.elapsedMs >= 3_000;

  return (
    <div className="space-y-6">
      <section aria-labelledby="cards-title">
        <h3 id="cards-title" className="label-micro mb-3">
          Synthèse
        </h3>
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <MetricCard
            label="Véhicules uniques"
            value={stats.uniqueVehicles.toString()}
            hint="Tous types confondus"
          />
          <MetricCard
            label="Franchissements"
            value={stats.crossings.toString()}
            hint="Somme des deux sens"
          />
          <MetricCard
            label="Ré-identifications"
            value={stats.reidHits.toString()}
            hint="Retours après occlusion"
          />
          <MetricCard
            label="Débit estimé"
            value={rateAvailable ? `${stats.vehiclesPerMinute}` : "—"}
            hint={
              rateAvailable ? "Véhicules par minute" : "Disponible après 3 s de flux analysé"
            }
          />
          <MetricCard
            label="Objets suivis"
            value={stats.activeTracks.toString()}
            hint="Pistes vivantes à cet instant"
          />
          <MetricCard
            // **« serveur » explicite** : ce n'est pas la cadence de lecture de la
            // vidéo, et les deux chiffres se confondraient sans cette étiquette.
            label="Cadence (serveur)"
            value={processingFps > 0 ? processingFps.toFixed(1) : "—"}
            hint="Images analysées par seconde"
          />
        </div>
        <p className="mt-2 text-small text-ink-dim">
          {formatSceneTime(stats.analysedSceneMs)} de flux analysé
          {!rateAvailable && " — débit disponible après 3 s de flux"}
        </p>
      </section>

      <section aria-labelledby="classes-title">
        <h3 id="classes-title" className="label-micro mb-3">
          Répartition par type
        </h3>
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          {VEHICLE_CLASSES.map((klass) => (
            <div key={klass} className="rounded-card bg-surface p-3 shadow-card">
              <p className="text-caption font-bold text-ink">{classLabel(klass)}</p>
              <p className="mt-1 text-small text-ink-muted tabular">
                {stats.uniqueByClass[klass] ?? 0} uniques · {stats.byClass[klass] ?? 0} passages
              </p>
            </div>
          ))}
        </div>
        {/* La règle de l'invariant 4, énoncée à l'utilisateur : on compte sous
            l'identité votée, pas sous la lecture de la frame courante. */}
        <p className="mt-2 text-small text-ink-dim">
          Le type retenu pour un véhicule est celui que le détecteur lui a donné le
          plus souvent, pas celui de la dernière image.
        </p>
      </section>

      {children}

      {lines.length > 0 && (
        <section aria-labelledby="lines-title">
          <h3 id="lines-title" className="label-micro mb-3">
            Détail par ligne
          </h3>
          <ul className="space-y-2">
            {lines.map((line) => {
              const tally = stats.byLine[line.id];
              const zone = zones.find((candidate) => candidate.id === line.zoneId);
              return (
                <li
                  key={line.id}
                  className="flex flex-wrap items-center gap-x-4 gap-y-1 rounded-card bg-surface p-3 shadow-card"
                >
                  <span
                    aria-hidden="true"
                    className="size-3 shrink-0 rounded-badge"
                    style={{ backgroundColor: line.color }}
                  />
                  <span className="text-caption font-bold text-ink">{line.name}</span>
                  <span className="text-small text-ink-dim">
                    {zone === undefined ? "toute l'image" : `zone : ${zone.name}`}
                  </span>
                  <span
                    className="text-caption text-ink-muted tabular"
                    title="Passages par sens relatif au tracé A→B. Un aller-retour compte une fois dans chaque sens."
                  >
                    ↑ {tally?.byDirection.positive ?? 0} · ↓ {tally?.byDirection.negative ?? 0}
                  </span>
                  <span className="ms-auto text-caption font-bold text-ink tabular">
                    {tally?.total ?? 0}
                  </span>
                </li>
              );
            })}
          </ul>
        </section>
      )}

      {zones.length > 0 && (
        <section aria-labelledby="zones-title">
          <h3 id="zones-title" className="label-micro mb-3">
            Détail par zone
          </h3>
          <ul className="space-y-2">
            {zones.map((zone) => {
              const tally = stats.byZone[zone.id];
              return (
                <li
                  key={zone.id}
                  className="flex flex-wrap items-center gap-x-4 gap-y-1 rounded-card bg-surface p-3 shadow-card"
                >
                  <span
                    aria-hidden="true"
                    className="size-3 shrink-0 rounded-badge"
                    style={{ backgroundColor: zone.color }}
                  />
                  <span className="text-caption font-bold text-ink">{zone.name}</span>
                  <span className="text-small text-ink-muted tabular">
                    {tally?.entries ?? 0} entrées uniques
                  </span>
                  {/* En relecture, l'occupation instantanée n'est pas
                      reconstituable : le serveur ne renvoie pas l'appartenance
                      par frame. On le **dit** plutôt que d'afficher un 0 trompeur. */}
                  <span className="text-small text-ink-dim tabular">
                    {replaying ? "présents : —" : `${tally?.inside ?? 0} présents`}
                  </span>
                </li>
              );
            })}
          </ul>
          {replaying && (
            <p className="mt-2 text-small text-ink-dim">
              L'occupation instantanée d'une zone n'est pas rejouable : elle
              s'affiche sur le résultat complet, pas à une position de lecture.
            </p>
          )}
        </section>
      )}
    </div>
  );
}
