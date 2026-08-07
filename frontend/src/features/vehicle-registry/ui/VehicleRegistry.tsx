/**
 * Le registre des véhicules.
 *
 * **Pourquoi ce tableau existe** : les cartes disent *combien*, le registre dit
 * *lesquels*. C'est ce qui rend un total **vérifiable** plutôt que croyable — on
 * peut pointer une ligne, retrouver le véhicule dans la vidéo, et confirmer. Sans
 * lui, « 47 véhicules » est un acte de foi.
 *
 * Trois comportements d'affichage, chacun pour une raison mesurée :
 * - **12 lignes puis « Afficher les N restants »** : le registre est sous les
 *   cartes, et déployer 400 lignes par défaut repousserait tout le reste hors écran ;
 * - **virtualisation au-delà de 200 lignes** : 10 000 lignes de tableau bloquent
 *   l'onglet plusieurs secondes à chaque rendu ;
 * - **note de bas de tableau quand aucune échelle px/m n'est fournie** : sinon la
 *   colonne « Vitesse » en px/s se lit comme une valeur inutilisable, alors qu'elle
 *   est simplement dans une autre unité.
 */

import { useCallback, useDeferredValue, useEffect, useMemo, useRef, useState } from "react";

import { directionLabel, formatSceneTime, formatScore, formatSpeed } from "@/features/results-dashboard";
import type { AnalysisResult, VehicleRecord } from "@/shared/api/contracts";
import { classColor } from "@/shared/config/palettes";
import { plateCell, plateTitle } from "@/shared/lib/plate";
import { Button } from "@/shared/ui/Button";

import {
  crossingsCsv,
  downloadText,
  exportFilename,
  resultJson,
  vehiclesCsv,
} from "../model/exportCsv";
import { filterByPlate } from "../model/filterPlate";
import { plateUnreadLabel, plateUnreadMessage } from "../model/plateUnread";
import { INITIAL_ROWS, ROW_HEIGHT, shouldVirtualise, visibleWindow } from "../model/virtualise";

interface VehicleRegistryProps {
  result: AnalysisResult;
  /** Véhicules à afficher — filtrés par la tête de lecture en relecture. */
  vehicles: readonly VehicleRecord[];
  /** Noms des lignes, pour libeller les puces de franchissement. */
  lineNames: ReadonlyMap<string, string>;
  /** Vrai si une échelle px/m a été fournie : change l'unité de la colonne vitesse. */
  hasScale: boolean;
}

/** Hauteur du conteneur virtualisé. */
const VIEWPORT_HEIGHT = 420;

export function VehicleRegistry({
  result,
  vehicles,
  lineNames,
  hasScale,
}: VehicleRegistryProps) {
  const [expanded, setExpanded] = useState(false);
  const [scrollTop, setScrollTop] = useState(0);
  // L'état de recherche vit **ici**, comme `expanded` et `scrollTop` : c'est un état de
  // vue de ce tableau. Le hisser dans `StudioPage` ferait remonter chaque frappe dans le
  // composant qui rend aussi le canvas. La règle « le câblage passe par StudioPage »
  // vise les dépendances **entre features**, pas l'état interne d'un composant.
  const [plateQuery, setPlateQuery] = useState("");
  // Le champ répond au clavier, le tableau rattrape. Pas de debounce maison : React sait
  // déjà déprioriser ce rendu, et il n'existe aucun utilitaire de debounce dans ce dépôt.
  const deferredQuery = useDeferredValue(plateQuery);
  const scroller = useRef<HTMLDivElement>(null);

  const filtered = useMemo(() => filterByPlate(vehicles, deferredQuery), [vehicles, deferredQuery]);

  const virtualised = expanded && shouldVirtualise(filtered.length);
  const shown = expanded ? filtered : filtered.slice(0, INITIAL_ROWS);
  const remaining = filtered.length - shown.length;

  const window = useMemo(
    () =>
      virtualised
        ? visibleWindow(filtered.length, scrollTop, VIEWPORT_HEIGHT)
        : { start: 0, end: shown.length, totalHeight: 0, offsetTop: 0 },
    [virtualised, filtered.length, scrollTop, shown.length],
  );

  const rows = virtualised ? filtered.slice(window.start, window.end) : shown;

  const handleScroll = useCallback(() => {
    const element = scroller.current;
    if (element !== null) setScrollTop(element.scrollTop);
  }, []);

  // Remise à zéro du défilement quand la recherche change : sinon `visibleWindow`
  // calcule une fenêtre au-delà de la fin d'un jeu réduit, et le tableau **paraît vide**
  // alors qu'il contient des lignes.
  useEffect(() => {
    setScrollTop(0);
    if (scroller.current !== null) scroller.current.scrollTop = 0;
  }, [deferredQuery]);

  // Ce garde reste sur la liste **non filtrée** : il annoncerait sinon un registre vide
  // alors que c'est la recherche qui ne rend rien — deux causes très différentes.
  if (vehicles.length === 0) {
    return (
      <section aria-labelledby="registry-title">
        <h3 id="registry-title" className="label-micro mb-3">
          Registre des véhicules
        </h3>
        <p className="rounded-card bg-surface p-4 text-caption text-ink-dim shadow-card">
          Aucun véhicule identifié pour l'instant. Le registre se remplit au fil de
          l'analyse.
        </p>
      </section>
    );
  }

  const table = (
    <table className="w-full border-collapse text-small">
      <thead>
        <tr className="text-start">
          <Th className="w-12">#</Th>
          <Th className="w-24">Type</Th>
          <Th className="w-32">Vu de / à</Th>
          <Th>Lignes franchies</Th>
          <Th className="w-24">Vitesse</Th>
          <Th className="w-16">Ré-id</Th>
          {/* Deux colonnes et non une cellule à deux valeurs : une cellule sur deux
              lignes casserait `ROW_HEIGHT`, dont la virtualisation dépend. `w-20`
              tenait « 71 % » mais ni `AB-123-CD` ni « illisible ». */}
          <Th className="w-28">Plaque</Th>
          <Th className="w-20">Conf. lecture</Th>
        </tr>
      </thead>
      <tbody>
        {rows.map((vehicle) => (
          <tr
            key={vehicle.globalId}
            style={{ height: ROW_HEIGHT }}
            className="border-t border-line/40"
          >
            <Td className="font-bold text-ink tabular">{vehicle.globalId}</Td>
            <Td>
              <span className="flex items-center gap-1.5">
                <span
                  aria-hidden="true"
                  className="size-2 rounded-badge"
                  style={{ backgroundColor: classColor(vehicle.label) }}
                />
                {vehicle.label}
              </span>
            </Td>
            <Td className="tabular">
              {formatSceneTime(vehicle.firstSeenMs)} → {formatSceneTime(vehicle.lastSeenMs)}
            </Td>
            <Td>
              {vehicle.crossedLines.length === 0 ? (
                <span className="text-ink-dim">—</span>
              ) : (
                <span className="flex flex-wrap gap-1">
                  {vehicle.crossedLines.map((crossing, index) => (
                    <span
                      key={`${crossing.lineId}-${crossing.timestampMs}-${index}`}
                      // L'infobulle donne la ligne, l'instant **et** le sens :
                      // c'est ce qui permet de retrouver le passage dans la vidéo.
                      title={`${lineNames.get(crossing.lineId) ?? crossing.lineId} à ${formatSceneTime(crossing.timestampMs)}, sens ${directionLabel(crossing.direction)}`}
                      className="rounded-badge bg-elevated px-1.5 py-0.5 text-micro"
                    >
                      {crossing.direction > 0 ? "↑" : "↓"}{" "}
                      {lineNames.get(crossing.lineId) ?? crossing.lineId}
                    </span>
                  ))}
                </span>
              )}
            </Td>
            <Td className="tabular">
              {formatSpeed(vehicle.avgSpeedKmh, vehicle.avgSpeedPxS)}
            </Td>
            <Td className="tabular">
              {vehicle.reidCount > 0 ? `↻ ${vehicle.reidCount}` : "—"}
            </Td>
            <Td
              // Le texte lu est de l'information de premier plan ; « illisible » et
              // « — » sont des états, donc atténués. C'est la couleur qui dit « ceci
              // est une lecture » sans ajouter un mot dans la cellule.
              className={vehicle.plateText === null ? "text-ink-dim" : "tabular text-ink"}
            >
              {/* Jamais une cellule vide : « rien » se lirait « pas de plaque » alors
                  que `bestPlateScore` prouve le contraire.

                  Quand le serveur dit **pourquoi**, sa raison l'emporte sur le
                  générique « illisible » : « trop petite » et « non détectée »
                  appellent deux gestes différents, et l'infobulle porte la phrase
                  complète avec la largeur mesurée. C'est ce qui distingue « la
                  chaîne refuse d'inventer » d'une panne du service — et
                  l'étranglement du détecteur comme le plancher de lecture rendent
                  ce silence plus fréquent, pas moins. */}
              <span
                title={
                  vehicle.plateText === null && vehicle.plateUnreadReason !== null
                    ? plateUnreadMessage(
                        vehicle.plateUnreadReason,
                        vehicle.plateBestWidthPx,
                      )
                    : plateTitle(
                        vehicle.plateText,
                        vehicle.plateTextScore,
                        vehicle.bestPlateScore,
                      )
                }
              >
                {vehicle.plateText === null && vehicle.plateUnreadReason !== null
                  ? plateUnreadLabel(vehicle.plateUnreadReason)
                  : plateCell(vehicle.plateText, vehicle.bestPlateScore)}
              </span>
            </Td>
            <Td className="tabular">{formatScore(vehicle.plateTextScore)}</Td>
          </tr>
        ))}
      </tbody>
    </table>
  );

  return (
    <section aria-labelledby="registry-title">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <h3 id="registry-title" className="label-micro">
          Registre des véhicules
        </h3>
        <div className="flex flex-wrap items-center gap-2">
          <label className="flex items-center gap-2">
            <span className="sr-only">Rechercher une plaque</span>
            <input
              type="search"
              value={plateQuery}
              onChange={(event) => setPlateQuery(event.target.value)}
              maxLength={16}
              // Un exemple plutôt qu'une consigne : il montre du même coup que la
              // ponctuation et la casse n'ont pas d'importance.
              placeholder="Plaque — ex. 2418tbe"
              className="w-44 rounded-input bg-elevated px-3 py-1.5 text-small text-ink placeholder:text-ink-dim"
            />
          </label>
          {/* Les exports restent sur `result` complet : un CSV amputé par une recherche
              à l'écran serait un fichier dont personne ne saurait ce qu'il contient. */}
          <Button
            size="sm"
            variant="ghost"
            onClick={() =>
              downloadText(
                exportFilename(result.jobId, "vehicules", "csv"),
                vehiclesCsv(result),
                "text/csv",
              )
            }
          >
            CSV véhicules
          </Button>
          <Button
            size="sm"
            variant="ghost"
            onClick={() =>
              downloadText(
                exportFilename(result.jobId, "franchissements", "csv"),
                crossingsCsv(result),
                "text/csv",
              )
            }
          >
            CSV franchissements
          </Button>
          <Button
            size="sm"
            variant="ghost"
            onClick={() =>
              downloadText(
                exportFilename(result.jobId, "resultat", "json"),
                resultJson(result),
                "application/json",
              )
            }
          >
            JSON
          </Button>
        </div>
      </div>

      {/* Le second vide, distinct de celui du registre entier. Sans le bouton
          d'effacement, un utilisateur qui a tapé une plaque absente voit un tableau vide
          et conclut que l'analyse a échoué. */}
      {filtered.length === 0 ? (
        <p className="rounded-card bg-surface p-4 text-caption text-ink-dim shadow-card">
          Aucune plaque ne contient « {plateQuery} ».{" "}
          <button
            type="button"
            onClick={() => setPlateQuery("")}
            className="underline transition-colors hover:text-ink"
          >
            Effacer la recherche
          </button>
        </p>
      ) : (
      <div className="overflow-hidden rounded-card bg-surface shadow-card">
        {virtualised ? (
          <div
            ref={scroller}
            onScroll={handleScroll}
            style={{ height: VIEWPORT_HEIGHT }}
            className="overflow-y-auto"
          >
            {/* Le conteneur porte la hauteur totale pour que la barre de
                défilement soit juste ; le contenu est décalé de `offsetTop`. */}
            <div style={{ height: window.totalHeight, position: "relative" }}>
              <div style={{ transform: `translateY(${window.offsetTop}px)` }}>{table}</div>
            </div>
          </div>
        ) : (
          <div className="overflow-x-auto">{table}</div>
        )}
      </div>
      )}

      {remaining > 0 && (
        <button
          type="button"
          onClick={() => setExpanded(true)}
          className="mt-2 text-small text-ink-muted underline transition-colors hover:text-ink"
        >
          Afficher les {remaining} véhicules restants
        </button>
      )}

      {!hasScale && (
        // Sans cette note, une colonne en px/s se lit comme inutilisable — alors
        // qu'elle est simplement dans une autre unité, faute d'échelle.
        <p className="mt-2 text-small text-ink-dim">
          Les vitesses sont en pixels par seconde : renseignez l'échelle (px/m) dans
          les réglages pour les obtenir en km/h.
        </p>
      )}
    </section>
  );
}

function Th({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return (
    <th
      scope="col"
      className={`px-3 py-2 text-start text-micro font-semibold uppercase tracking-wider text-ink-dim ${className}`}
    >
      {children}
    </th>
  );
}

function Td({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return <td className={`px-3 py-1.5 text-ink-muted ${className}`}>{children}</td>;
}
