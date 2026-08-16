/**
 * Le tableau de résultats : cartes, synthèse, répartition, détail par sens.
 *
 * Un principe traverse tous ces affichages : **chaque chiffre dit d'où il vient**.
 * « Cadence (serveur) » et non « Cadence », « Entrées au carrefour » et non
 * « Entrées », le nom du sens plutôt qu'une flèche. Sans ces précisions, deux
 * chiffres voisins qui ne mesurent pas la même chose se confondent, et l'utilisateur
 * tire une conclusion fausse sans jamais s'en douter.
 *
 * Deux unités cohabitent, et il ne faut jamais les diviser l'une par l'autre :
 *
 * - **véhicules** — `trackedVehicles`, `crossedUnique`. Un objet suivi, un véhicule ;
 * - **passages** — `crossings`, tous les `byLine`. Un aller-retour en vaut deux.
 *
 * C'est l'invariant 3, et il a déjà coûté un « taux de franchissement » à 200 %.
 */

import type { ReactNode } from "react";

import type { AnalysisStats, CountingLine, VehicleRecord, Zone } from "@/shared/api/contracts";
import { MetricCard } from "@/shared/ui/MetricCard";

import {
  type DirectionRow,
  directionRows,
  flowBalance,
  movements,
} from "../model/directions";
import {
  VEHICLE_CLASSES,
  classLabel,
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
   * La répartition, le détail par sens et le détail par zone vivent désormais dans
   * les onglets sous la vidéo : les rendre ici aussi les afficherait deux fois.
   */
  cardsOnly?: boolean;
  /**
   * Contenu inséré **entre la répartition par type et le détail par sens**.
   *
   * Un emplacement et non une place libre en bas : ce qui vient s'y loger — le
   * journal des franchissements pendant une analyse — se lit juste après les
   * totaux qu'il détaille, et juste avant le détail qui les répartit.
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
  const flow = flowBalance(stats, lines);

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
          {/* « — » et non « 0 » quand aucun rôle n'est déclaré : deux zéros se
              liraient comme « personne n'entre », alors que la vérité est
              « personne ne l'a encore dit » — le seul cas restant est l'absence de
              toute ligne, le rôle étant obligatoire depuis ADR 0021. */}
          <MetricCard
            label="Entrées au carrefour"
            value={flow.declared ? flow.entries.toString() : "—"}
            // Somme des passages sur tous les sens marqués « entrée », toutes lignes
            // confondues : c'est le nombre de véhicules qui rentrent dans le
            // carrefour, pas seulement sur une ligne prise isolément.
            hint={
              flow.declared
                ? "Total des passages sur les sens marqués « entrée », toutes lignes"
                : "Ajoutez une ligne dans Géométrie pour obtenir ce chiffre"
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
            label="Flux analysé"
            value={formatSceneTime(stats.analysedSceneMs)}
            // Temps de **scène**, pas temps mural : c'est la durée de vidéo déjà
            // traitée, pas le temps que le serveur a mis pour la traiter.
            hint="Durée de vidéo déjà traitée par le serveur"
          />
        </div>
      </section>

      {cardsOnly ? null : (
        <>
          <ClassBreakdown stats={stats} lines={lines} />
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
 * **Plus aucun « unique ».** La colonne annonçait un nombre de véhicules
 * ré-identifiés qui ne tenait pas sa promesse d'unicité (ADR 0016) ; elle dit
 * maintenant « détectés », ce qui est exactement ce qu'elle compte.
 *
 * Trois chiffres par type, et chacun répond à une question différente : combien de
 * véhicules de ce type ont été vus, combien de passages ils ont produit, et quelle
 * part du trafic cela représente. Une barre porte la part, parce qu'un pourcentage se
 * compare mal de tête entre cinq tuiles.
 */
export function ClassBreakdown({
  stats,
  lines,
}: {
  stats: AnalysisStats;
  lines: readonly CountingLine[];
}) {
  // `person` en dernier : les véhicules d'abord, parce que c'est ce que
  // l'application compte par défaut, et la catégorie à part ensuite.
  const rows = [...VEHICLE_CLASSES, "person"] as const;
  const perDirection = directionRows(stats, lines);

  return (
    <section aria-labelledby="classes-title">
      <h3 id="classes-title" className="label-micro mb-3">
        Répartition par type
      </h3>
      <ul className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
        {rows.map((klass) => {
          const passages = stats.byClass[klass] ?? 0;
          const share = stats.crossings === 0 ? 0 : passages / stats.crossings;
          return (
            <li key={klass} className="rounded-card bg-surface p-3 shadow-card">
              <p className="text-caption font-bold text-ink">{classLabel(klass)}</p>
              <p className="mt-1 text-small text-ink-muted tabular">
                {stats.trackedByClass[klass] ?? 0} détectés · {passages} passages
              </p>
              {/* La barre est décorative : le chiffre au-dessus porte la même
                  information, et un lecteur d'écran n'a pas à entendre deux fois. */}
              <div
                aria-hidden="true"
                className="mt-2 h-1 overflow-hidden rounded-pill bg-elevated"
              >
                <div
                  className="h-full rounded-pill bg-ink-dim"
                  style={{ width: `${Math.round(share * 100)}%` }}
                />
              </div>
              <p className="mt-1 text-micro text-ink-dim tabular">
                {stats.crossings === 0 ? "—" : `${Math.round(share * 100)} % des passages`}
              </p>
              {/* La ventilation par sens **de ce type** : c'est ce qui permet de dire
                  « les camions entrent surtout par le nord », qu'un total fusionné ne
                  sait pas distinguer. */}
              <ul className="mt-2 space-y-0.5">
                {perDirection
                  .filter((row) => (row.tally.byClass[klass] ?? 0) > 0)
                  .map((row) => (
                    <li
                      key={`${row.lineId}-${row.sign}`}
                      className="flex items-baseline gap-1.5 text-micro text-ink-dim"
                    >
                      <span
                        aria-hidden="true"
                        className="size-1.5 shrink-0 rounded-badge"
                        style={{ backgroundColor: row.color }}
                      />
                      <span className="truncate">{row.name}</span>
                      <span className="ms-auto tabular">{row.tally.byClass[klass]}</span>
                    </li>
                  ))}
              </ul>
            </li>
          );
        })}
      </ul>
      {/* La règle de l'invariant 4, énoncée à l'utilisateur : on compte sous le type
          voté, pas sous la lecture de la frame courante. */}
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

/**
 * Le détail par ligne, **par sens**, et par zone.
 *
 * Chaque ligne se déplie en deux rangées nommées. C'est le remplacement du
 * « ↑ 12 · ↓ 8 » qui n'apprenait rien à qui n'a pas la convention A→B en tête : le
 * nom du sens est ce que l'utilisateur a écrit, donc ce qu'il comprend.
 */
export function LineAndZoneDetail({ stats, lines, zones, replaying }: DetailProps) {
  const rows = directionRows(stats, lines);

  return (
    <div className="space-y-6">
      {lines.length > 0 && (
        <section aria-labelledby="lines-title">
          <h3 id="lines-title" className="label-micro mb-3">
            Détail par ligne et par sens
          </h3>
          <ul className="space-y-3">
            {lines.map((line) => {
              const tally = stats.byLine[line.id];
              const zone = zones.find((candidate) => candidate.id === line.zoneId);
              const nearMisses = stats.diagnostics.nearMisses?.[line.id] ?? 0;
              return (
                <li key={line.id} className="rounded-card bg-surface p-3 shadow-card">
                  <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                    <span
                      aria-hidden="true"
                      className="size-3 shrink-0 rounded-badge"
                      style={{ backgroundColor: line.color }}
                    />
                    <span className="text-caption font-bold text-ink">{line.name}</span>
                    <span className="text-small text-ink-dim">
                      {zone === undefined ? "toute l'image" : `zone : ${zone.name}`}
                    </span>
                    <span className="ms-auto text-caption font-bold text-ink tabular">
                      {tally?.total ?? 0}
                    </span>
                  </div>

                  {/* Le seul message de cet écran qui parle du **tracé** et non du
                      trafic. Il n'apparaît que s'il y a quelque chose à corriger :
                      une ligne franchie normalement n'a pas à porter d'avertissement,
                      et un bandeau permanent finirait par ne plus être lu. */}
                  {nearMisses > 0 && (
                    <p className="mt-2 text-small text-warning">
                      <strong>
                        {nearMisses} piste{nearMisses > 1 ? "s" : ""} éteinte
                        {nearMisses > 1 ? "s" : ""} à portée de ce trait
                      </strong>{" "}
                      sans jamais le franchir. La ligne est peut-être posée là où le
                      suivi s'arrête — près d'un bord de l'image, ou trop loin de la
                      caméra pour que les véhicules restent détectés. Ces pistes ne
                      comptent dans aucun total ; les rattraper demande de reculer le
                      trait, pas de changer le comptage.
                    </p>
                  )}

                  <ul className="mt-2 space-y-1">
                    {rows
                      .filter((row) => row.lineId === line.id)
                      .map((row) => (
                        <DirectionDetail key={row.sign} row={row} />
                      ))}
                  </ul>
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

/** Une rangée de sens : son nom, son rôle, son total, sa part, son débit, ses types. */
function DirectionDetail({ row }: { row: DirectionRow }) {
  const classes = Object.entries(row.tally.byClass).sort(
    ([, left], [, right]) => right - left,
  );

  return (
    <li className="rounded-input bg-surface-2 px-2 py-1.5">
      <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
        {/* La flèche dit **quel** sens dans la convention du canvas ; le nom dit ce
            que ce sens signifie. Les deux ensemble, parce que l'un sans l'autre
            oblige à deviner. */}
        <span aria-hidden="true" className="shrink-0 text-ink-dim">
          {row.sign === "positive" ? "↑" : "↓"}
        </span>
        <span className="min-w-0 truncate text-caption text-ink">{row.name}</span>
        <RoleBadge role={row.role} />
        <span className="ms-auto shrink-0 text-caption font-bold text-ink tabular">
          {row.tally.total}
        </span>
        {row.shareOfLine !== null && (
          <span className="shrink-0 text-micro text-ink-dim tabular">
            {Math.round(row.shareOfLine * 100)} %
          </span>
        )}
      </div>

      <div className="mt-0.5 flex flex-wrap items-baseline gap-x-3 text-micro text-ink-dim">
        {row.perMinute !== null && <span className="tabular">{row.perMinute} /min</span>}
        {classes.length > 0 && (
          <span className="tabular">
            {classes.map(([label, count]) => `${classLabel(label)} ${count}`).join(" · ")}
          </span>
        )}
        {/* Premier et dernier passage : c'est ce qui dit si un sens est actif tout du
            long ou seulement sur une pointe. `firstMs === null` signifie « aucun
            passage », et l'absence de cette ligne le dit déjà. */}
        {row.tally.firstMs !== null && row.tally.lastMs !== null && (
          <span className="tabular">
            {formatSceneTime(row.tally.firstMs)} → {formatSceneTime(row.tally.lastMs)}
          </span>
        )}
      </div>
    </li>
  );
}

function RoleBadge({ role }: { role: DirectionRow["role"] }) {
  if (role === "neutral") return null;
  const label = role === "entry" ? "entrée" : "sortie";
  return (
    <span className="shrink-0 rounded-badge bg-elevated-2 px-1.5 text-micro text-ink-muted">
      {label}
    </span>
  );
}

/**
 * La matrice origine-destination — « entré par où, ressorti par où ».
 *
 * L'onglet qui répond à la question d'un carrefour, et que ni les totaux par ligne ni
 * les totaux par sens ne savent poser : il faut savoir ce qu'un **même** véhicule a
 * franchi, et dans quel ordre.
 *
 * Un tableau plutôt qu'une matrice carrée, et c'est un choix de lisibilité : avec
 * quatre lignes on aurait huit sens, donc 64 cases dont la plupart vides. La liste
 * triée met le mouvement dominant en tête, qui est ce qu'on cherche en ouvrant
 * l'onglet.
 */
export function MovementMatrix({
  vehicles,
  lines,
  available,
}: {
  vehicles: readonly VehicleRecord[];
  lines: readonly CountingLine[];
  /**
   * Le registre est-il disponible ?
   *
   * Faux pendant une analyse et en direct : l'aperçu SSE ne transporte pas les
   * véhicules. **Le dire** plutôt que d'afficher une matrice vide, qui se lirait
   * comme « aucun véhicule ne tourne ».
   */
  available: boolean;
}) {
  const rows = available ? movements(vehicles, lines) : [];

  return (
    <section aria-labelledby="movements-title">
      <h3 id="movements-title" className="label-micro mb-3">
        Mouvements observés
      </h3>

      {!available ? (
        <p className="text-small text-ink-dim">
          Les mouvements se calculent sur un résultat complet : ils demandent de savoir
          ce qu'un même véhicule a franchi, et l'aperçu d'une analyse en cours ne porte
          pas encore le registre.
        </p>
      ) : rows.length === 0 ? (
        <p className="text-small text-ink-dim">
          Aucun véhicule n'a franchi deux lignes. Un mouvement demande deux
          franchissements successifs : avec une seule ligne, il n'y a pas de trajet à
          décrire.
        </p>
      ) : (
        <>
          <ul className="space-y-1">
            {rows.map((row) => (
              <li
                key={`${row.from.lineId}:${row.from.sign}>${row.to.lineId}:${row.to.sign}`}
                className="flex flex-wrap items-baseline gap-x-2 gap-y-1 rounded-card bg-surface px-3 py-2 shadow-card"
              >
                <span className="min-w-0 truncate text-caption text-ink">{row.from.name}</span>
                <span aria-hidden="true" className="shrink-0 text-ink-dim">
                  →
                </span>
                <span className="min-w-0 truncate text-caption text-ink">{row.to.name}</span>
                <span className="shrink-0 text-micro text-ink-dim">
                  {row.from.lineName} → {row.to.lineName}
                </span>
                <span className="ms-auto shrink-0 text-caption font-bold text-ink tabular">
                  {row.count}
                </span>
                <span className="shrink-0 text-micro text-ink-dim tabular">
                  {Math.round(row.share * 100)} %
                </span>
              </li>
            ))}
          </ul>
          {/* Les deux limites énoncées, plutôt que découvertes en additionnant. */}
          <p className="mt-2 text-small text-ink-dim">
            Un véhicule qui franchit trois lignes produit deux mouvements : la somme
            décrit des trajets, pas des véhicules. Un véhicule qui n'a franchi qu'une
            ligne n'apparaît pas ici, tout en comptant dans les totaux.
          </p>
        </>
      )}
    </section>
  );
}
