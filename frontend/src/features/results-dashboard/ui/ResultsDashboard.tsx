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

import {
  VEHICLE_CLASSES,
  classLabel,
  crossingRate,
  formatCrossingRate,
  formatFrameLatency,
  formatSceneTime,
} from "../model/labels";

interface ResultsDashboardProps {
  stats: AnalysisStats;
  lines: readonly CountingLine[];
  zones: readonly Zone[];
  /** Cadence de traitement du **serveur**, distincte de la lecture vidéo. */
  processingFps: number;
  /** Vrai en relecture : l'occupation de zone n'est alors pas calculable. */
  replaying: boolean;
  /**
   * Disposition des cartes.
   *
   * - `wide` — quatre colonnes en pleine largeur. Le direct et l'analyse en cours,
   *   où le tableau de bord occupe toute la page ;
   * - `column` — deux colonnes serrées, pour la colonne latérale du studio, où les
   *   chiffres se lisent **à côté** de la scène plutôt qu'en dessous.
   *
   * Une prop plutôt qu'un second composant : c'est le même code qui sert le direct et
   * le différé, et c'est précisément ce qui garantit que les deux modes affichent les
   * mêmes chiffres. Dupliquer la grille dupliquerait tôt ou tard une carte.
   */
  layout?: "wide" | "column";
  /**
   * N'affiche que les cartes de synthèse.
   *
   * La répartition, le détail par ligne et le détail par zone vivent désormais dans
   * les onglets sous la vidéo : les rendre ici aussi les afficherait deux fois.
   */
  cardsOnly?: boolean;
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
  layout = "wide",
  cardsOnly = false,
  children,
}: ResultsDashboardProps) {
  const rateAvailable = stats.elapsedMs >= 3_000;

  return (
    <div className="space-y-6">
      <section aria-labelledby="cards-title">
        <h3 id="cards-title" className="label-micro mb-3">
          Résultats
        </h3>
        <div
          className={
            layout === "column"
              ? "grid grid-cols-2 gap-2"
              : "grid gap-3 sm:grid-cols-2 xl:grid-cols-4"
          }
        >
          {/* Les deux cartes de tête sont les catégories, jamais leur somme : un
              piéton n'est pas un véhicule de plus. La somme des deux **est**
              « Franchissements », que le serveur garantit égale (ADR 0014). */}
          <MetricCard
            label="Passages de véhicules"
            value={(stats.byCategory.vehicle ?? 0).toString()}
            hint="Voitures, motos, bus, camions, vélos"
          />
          <MetricCard
            label="Passages de personnes"
            value={(stats.byCategory.person ?? 0).toString()}
            hint="Comptées à part des véhicules"
          />
          <MetricCard
            label="Franchissements"
            value={stats.crossings.toString()}
            // Ce que le chiffre compte **vraiment** depuis ADR 0014 : des
            // passages. Un aller-retour en vaut deux, et deux lignes en travers
            // de la même voie en valent deux. Le dire ici évite qu'on le
            // découvre en comparant deux tableaux.
            hint="Passages observés, tous sens — un aller-retour compte 2"
          />
          <MetricCard
            label="Objets uniques"
            value={stats.uniqueVehicles.toString()}
            hint="Identités suivies, pas le total compté"
          />
          {/* La carte « Ré-identifications » a été retirée. La ré-identification est
              **sortie du périmètre produit** (ADR 0014) : on compte des passages, et
              `reidHits` ne décrit plus rien que l'utilisateur arbitre. Le champ reste
              dans le contrat — la galerie tourne toujours pour le vote de classe et
              le vote de plaque — mais l'afficher invitait à interpréter un rouage
              interne comme un résultat. */}
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
          <MetricCard
            label="Latence moyenne"
            value={formatFrameLatency(processingFps)}
            // Dit ce que le chiffre mesure : le traitement d'une image côté
            // serveur, et non un aller-retour réseau — en différé, il n'y en a
            // pas par image.
            hint="Temps de traitement par image"
          />
          <MetricCard
            label="Taux de franchissement"
            value={formatCrossingRate(crossingRate(stats.uniqueVehicles, stats.crossedUnique))}
            // Ce que ni « uniques » ni « passages » ne disent seuls : la ligne
            // est-elle posée là où le trafic passe ?
            //
            // `crossedUnique` et non `crossings` : depuis ADR 0014 les passages sont
            // une autre unité que les véhicules, et les diviser l'un par l'autre
            // faisait dépasser 100 % dès le premier aller-retour.
            hint="Part des véhicules vus qui franchissent une ligne"
          />
        </div>
        <p className="mt-2 text-small text-ink-dim">
          {formatSceneTime(stats.analysedSceneMs)} de flux analysé
          {!rateAvailable && " — débit disponible après 3 s de flux"}
        </p>
      </section>

      {cardsOnly ? null : (
        <>
          <ClassBreakdown stats={stats} />
          {children}
          <LineAndZoneDetail stats={stats} lines={lines} zones={zones} replaying={replaying} />
        </>
      )}
    </div>
  );
}

/**
 * La répartition par type — véhicules **et** personnes.
 *
 * Extraite pour être posée dans un onglet sous la vidéo, et corrigée au passage :
 * elle n'itérait que les quatre classes de véhicules. Les personnes sont comptées
 * depuis ADR 0014, s'affichent dans les cartes de synthèse, et n'apparaissaient
 * nulle part ici — un total visible en haut sans aucune ligne correspondante en bas
 * se lit comme une incohérence du comptage.
 */
export function ClassBreakdown({ stats }: { stats: AnalysisStats }) {
  // `person` en dernier : les véhicules d'abord, parce que c'est ce que
  // l'application compte par défaut, et la catégorie à part ensuite.
  const rows = [...VEHICLE_CLASSES, "person"] as const;

  return (
    <section aria-labelledby="classes-title">
      <h3 id="classes-title" className="label-micro mb-3">
        Répartition par type
      </h3>
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
        {rows.map((klass) => (
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
        Le type retenu pour un véhicule est celui que le détecteur lui a donné le plus
        souvent, pas celui de la dernière image.
      </p>
    </section>
  );
}

interface DetailProps {
  stats: AnalysisStats;
  lines: readonly CountingLine[];
  zones: readonly Zone[];
  replaying: boolean;
}

/** Le détail par ligne et par zone — extrait pour tenir dans un onglet. */
export function LineAndZoneDetail({ stats, lines, zones, replaying }: DetailProps) {
  return (
    <div className="space-y-6">
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
