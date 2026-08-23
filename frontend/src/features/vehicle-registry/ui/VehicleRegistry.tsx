/**
 * Le registre des véhicules.
 *
 * **Pourquoi ce tableau existe** : les cartes disent *combien*, le registre dit
 * *lesquels*. C'est ce qui rend un total **vérifiable** plutôt que croyable — on
 * peut pointer une ligne, retrouver le véhicule dans la vidéo, et confirmer. Sans
 * lui, « 47 véhicules » est un acte de foi.
 *
 * **Il ne publie que les véhicules ayant franchi au moins une ligne**, tous sens
 * confondus — le filtre est appliqué par l'appelant (`crossingVehicles` dans
 * `StudioPage`), qui le partage avec le chiffre de tête du tableau de bord pour
 * que les deux parlent du même ensemble. Le serveur, lui, publie tout objet suivi
 * confirmé : stationnement compris. Ces lignes-là n'avaient que des « — » dans
 * les colonnes de franchissement et « Passages », donc rien à vérifier —
 * exactement ce que ce tableau existe pour permettre.
 *
 * Deux comportements d'affichage, chacun pour une raison mesurée :
 * - **12 lignes puis « Afficher les N restants »** : le registre est sous les
 *   cartes, et déployer 400 lignes par défaut repousserait tout le reste hors écran ;
 * - **virtualisation au-delà de 200 lignes** : 10 000 lignes de tableau bloquent
 *   l'onglet plusieurs secondes à chaque rendu.
 */

import { ArrowUp } from "lucide-react";
import { useCallback, useDeferredValue, useEffect, useMemo, useRef, useState } from "react";

import {
  formatSceneTime,
  formatSceneTimePrecise,
  formatScore,
} from "@/features/results-dashboard";
import type {
  AnalysisResult,
  CountingLine,
  DirectionRole,
  VehicleRecord,
} from "@/shared/api/contracts";
import { classColor } from "@/shared/config/palettes";
import { classLabel } from "@/shared/lib/classes";
import {
  crossingDirectionName,
  crossingHeadingDeg,
  directionArrow,
  lineName,
} from "@/shared/lib/directions";
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
import { plateBestGuessMessage, plateUnreadLabel, plateUnreadMessage } from "../model/plateUnread";
import { crossingsWithRole, crossingsWithoutRole } from "../model/roleCrossings";
import { INITIAL_ROWS, ROW_HEIGHT, shouldVirtualise, visibleWindow } from "../model/virtualise";

interface VehicleRegistryProps {
  /**
   * Le résultat complet, ou `null` **pendant** l'analyse.
   *
   * Il ne sert qu'aux exports : le tableau, lui, ne lit que `vehicles`. C'est ce
   * qui permet au registre de se remplir en cours d'analyse, alimenté par le
   * registre que l'aperçu SSE transporte — sans que rien ici sache d'où il vient.
   *
   * `null` **masque les trois boutons d'export**, et ce n'est pas une omission :
   * un CSV produit à mi-analyse serait un fichier dont personne ne saurait ce
   * qu'il contient — ni combien de véhicules manquent, ni lesquels. Même raison
   * que les exports qui ignorent la recherche à l'écran.
   */
  result: AnalysisResult | null;
  /** Véhicules à afficher — filtrés par la tête de lecture en relecture. */
  vehicles: readonly VehicleRecord[];
  /**
   * La géométrie courante, pour nommer les lignes **et les sens**.
   *
   * Les lignes entières et non une `Map` de noms : une puce de franchissement affiche
   * désormais le nom du *sens*, que seule la ligne complète permet de calculer — le
   * défaut géométrique se déduit de `a` et `b`.
   */
  lines: readonly CountingLine[];
}

/** Hauteur du conteneur virtualisé. */
const VIEWPORT_HEIGHT = 420;

export function VehicleRegistry({
  result,
  vehicles,
  lines,
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

  /**
   * Un franchissement échappe-t-il aux deux rôles, **quelque part** dans le
   * registre ?
   *
   * Sur `vehicles` et non sur les lignes rendues : une colonne qui apparaîtrait au
   * défilement d'un tableau virtualisé décalerait toutes les autres sous le
   * curseur. Elle existe donc pour tout le tableau, ou pour aucun.
   */
  const hasUnroled = useMemo(
    () => vehicles.some((entry) => crossingsWithoutRole(entry, lines).length > 0),
    [vehicles, lines],
  );

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
          {/* « encore » n'est pas un mot de remplissage : le registre se remplit
              maintenant *pendant* l'analyse, et cette phrase s'affiche donc surtout
              sur ses premières secondes — avant le premier franchissement. */}
          Aucun véhicule n'a encore franchi de ligne. Le registre se remplit au fil de
          l'analyse — les véhicules simplement détectés, à l'arrêt ou en stationnement,
          n'y figurent pas.
        </p>
      </section>
    );
  }

  const table = (
    <table className="w-full border-collapse text-small">
      <thead>
        <tr className="text-start">
          <Th className="w-12">#</Th>
          <Th className="w-28">Type</Th>
          {/* « Présent de / à » et non « Vu de / à » : le mot disait *que* le
              véhicule avait été vu, pas *quoi* — et se lisait comme l'heure du
              franchissement, que les colonnes « Entrée par » et « Sortie par »
              portent maintenant. Ce sont les bornes de la piste dans le champ de
              la caméra, franchissement ou pas. */}
          <Th className="w-32">Présent de / à</Th>
          {/* Précisé pour la même raison : la durée est un temps de **présence à
              l'écran**, jamais un temps de trajet entre deux lignes. */}
          <Th className="w-20">Durée à l'écran</Th>
          {/* **Par où et quand, rangés par rôle.** « Lignes franchies » listait les
              deux sens dans une seule cellule, et les deux colonnes voisines n'en
              portaient que l'heure : lire « ce véhicule est entré par la ligne 1 à
              00:34 » demandait de recoller trois cellules, dont une par survol.

              Deux colonnes et non une : entrée et sortie répondent à deux
              questions. Le nom de la ligne et l'heure tiennent sur **une seule
              rangée** dans chaque cellule — les empiler casserait `ROW_HEIGHT`,
              dont la virtualisation dépend. */}
          <Th className="w-44">Entrée par</Th>
          <Th className="w-44">Sortie par</Th>
          {/* N'existe que si une ligne du tableau en porte : un franchissement dont
              le rôle n'est plus lisible — ligne retirée du tracé, ou sens resté
              neutre sur un tracé antérieur à ADR 0021. Le ranger sous un rôle
              serait une invention ; le taire ferait diverger le registre de la
              colonne « Passages », qui le compte. */}
          {hasUnroled && <Th className="w-40">Hors rôle</Th>}
          <Th className="w-28">Zones</Th>
          {/* « Passages » remplace « Ré-id » : la ré-identification n'existe plus
              (ADR 0016), et le nombre de franchissements d'un véhicule est
              l'information qui rend une ligne du registre vérifiable — un 0 dit
              « vu, jamais compté ». */}
          <Th className="w-16">Passages</Th>
          {/* Deux colonnes et non une cellule à deux valeurs : une cellule sur deux
              lignes casserait `ROW_HEIGHT`, dont la virtualisation dépend. `w-20`
              tenait « 71 % » mais ni `AB-123-CD` ni « illisible ». */}
          <Th className="w-28">Plaque</Th>
          {/* Détection et lecture sont deux confiances distinctes du même
              véhicule : `bestPlateScore` dit « à quel point le rectangle est bien
              une plaque », `plateTextScore` dit « à quel point le texte lu est
              fiable ». Les confondre masquerait le cas d'une plaque bien
              localisée mais illisible, ou l'inverse. */}
          <Th className="w-20">Conf. détection</Th>
          <Th className="w-20">Conf. lecture</Th>
        </tr>
      </thead>
      <tbody>
        {rows.map((vehicle, index) => (
          <tr
            key={vehicle.globalId}
            style={{ height: ROW_HEIGHT }}
            className={`border-t border-line/40 transition-colors hover:bg-elevated/60 ${
              index % 2 === 1 ? "bg-elevated/20" : ""
            }`}
          >
            <Td className="font-bold text-ink tabular">{vehicle.globalId}</Td>
            <Td>
              <span className="flex items-center gap-1.5">
                <span
                  aria-hidden="true"
                  className="size-2 shrink-0 rounded-badge"
                  style={{ backgroundColor: classColor(vehicle.label) }}
                />
                {classLabel(vehicle.label)}
              </span>
            </Td>
            <Td className="tabular">
              {formatSceneTime(vehicle.firstSeenMs)} → {formatSceneTime(vehicle.lastSeenMs)}
            </Td>
            <Td className="tabular text-ink-muted">
              {formatSceneTime(vehicle.lastSeenMs - vehicle.firstSeenMs)}
            </Td>
            <RoleCrossingCell vehicle={vehicle} lines={lines} role="entry" />
            <RoleCrossingCell vehicle={vehicle} lines={lines} role="exit" />
            {hasUnroled && <UnroledCrossingCell vehicle={vehicle} lines={lines} />}
            <Td className="text-ink-muted">
              {vehicle.zonesVisited.length === 0 ? (
                <span className="text-ink-dim">—</span>
              ) : (
                vehicle.zonesVisited.join(", ")
              )}
            </Td>
            <Td className="tabular">
              {vehicle.crossedLines.length === 0 ? "—" : vehicle.crossedLines.length}
            </Td>
            <Td
              // Le texte lu est de l'information de premier plan ; « illisible » et
              // « — » sont des états, donc atténués. Le candidat non confirmé n'est
              // ni l'un ni l'autre : ce n'est pas une absence, c'est une valeur qui
              // reste à vérifier — d'où `text-warning`, plutôt que la même
              // atténuation que « rien à voir ».
              className={
                vehicle.plateText !== null
                  ? "tabular text-ink"
                  : vehicle.plateBestGuess !== null
                    ? "tabular text-warning"
                    : "text-ink-dim"
              }
            >
              {/* Jamais une cellule vide : « rien » se lirait « pas de plaque » alors
                  que `bestPlateScore` prouve le contraire.

                  Quand le serveur dit **pourquoi**, sa raison l'emporte sur le
                  générique « illisible » : « trop petite » et « non détectée »
                  appellent deux gestes différents, et l'infobulle porte la phrase
                  complète avec la largeur mesurée. C'est ce qui distingue « la
                  chaîne refuse d'inventer » d'une panne du service — et
                  l'étranglement du détecteur comme le plancher de lecture rendent
                  ce silence plus fréquent, pas moins.

                  Sous `no_consensus`, un candidat non confirmé remplace le libellé
                  générique « lecture incertaine » : c'est un indice, jamais une
                  publication — il ne se substitue donc jamais à `plateText`, il ne
                  fait qu'occuper la place où le silence, sinon, ne dirait rien de
                  plus qu'une raison. */}
              <span
                title={
                  vehicle.plateText !== null
                    ? plateTitle(vehicle.plateText, vehicle.plateTextScore, vehicle.bestPlateScore)
                    : vehicle.plateBestGuess !== null
                      ? plateBestGuessMessage(vehicle.plateBestGuess, vehicle.plateBestGuessScore)
                      : vehicle.plateUnreadReason !== null
                        ? plateUnreadMessage(vehicle.plateUnreadReason, vehicle.plateBestWidthPx)
                        : undefined
                }
              >
                {vehicle.plateText !== null
                  ? plateCell(vehicle.plateText, vehicle.bestPlateScore)
                  : vehicle.plateBestGuess !== null
                    ? `${vehicle.plateBestGuess} ?`
                    : vehicle.plateUnreadReason !== null
                      ? plateUnreadLabel(vehicle.plateUnreadReason)
                      : plateCell(vehicle.plateText, vehicle.bestPlateScore)}
              </span>
            </Td>
            <Td className="tabular">{formatScore(vehicle.bestPlateScore)}</Td>
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
              à l'écran serait un fichier dont personne ne saurait ce qu'il contient.
              **La même règle explique leur absence pendant l'analyse** : `result`
              est alors `null`, et un export à mi-parcours serait amputé de tout ce
              qui reste à analyser, sans dire de combien. */}
          {result !== null && (
            <>
          <Button
            size="sm"
            variant="ghost"
            onClick={() =>
              downloadText(
                exportFilename(result.jobId, "vehicules", "csv"),
                vehiclesCsv(result, lines),
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
                crossingsCsv(result, lines),
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
            </>
          )}
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

    </section>
  );
}

/**
 * La flèche d'une puce de « Lignes franchies », **pivotée à l'angle réel du tracé**.
 *
 * Elle remplace le glyphe `↑` / `↓`, qui disait seulement « sens positif » ou « sens
 * négatif » — le contrat machine, invérifiable devant une image. Une flèche
 * perpendiculaire au trait dit ce que le nom du sens ne dit pas : **par où**. C'est le
 * même angle, par la même fonction partagée, que celui du panneau de géométrie, du
 * canvas et de la chronologie des franchissements — trois écrans, une flèche.
 *
 * `ArrowUp` pivotée en CSS et non un glyphe unicode, qui ne tourne qu'à 45° près : sur
 * une ligne oblique, « presque perpendiculaire » est précisément ce qui fait douter du
 * sens affiché.
 *
 * **Repli sur le glyphe quand la ligne n'est plus dans le tracé** — et non l'absence de
 * flèche comme dans la chronologie. La différence tient au texte à côté : là-bas le
 * libellé de repli est « sens ↑ », qui porte déjà le glyphe ; ici c'est l'identifiant
 * de la ligne, donc retirer la flèche ferait disparaître le sens de la puce.
 */
function CrossingArrow({
  lines,
  lineId,
  direction,
}: {
  lines: readonly CountingLine[];
  lineId: string;
  direction: number;
}) {
  const headingDeg = crossingHeadingDeg(lines, lineId, direction);

  if (headingDeg === null) {
    return <span aria-hidden="true">{directionArrow(direction)}</span>;
  }

  return (
    <ArrowUp
      aria-hidden="true"
      size={10}
      className="shrink-0"
      style={{ transform: `rotate(${headingDeg}deg)` }}
    />
  );
}

function Th({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return (
    <th
      scope="col"
      // `sticky top-0` : le tableau non virtualisé peut aussi dépasser la
      // hauteur de l'écran (400 lignes, jusqu'à 200 avant virtualisation) — les
      // en-têtes doivent rester lisibles pendant le défilement.
      className={`sticky top-0 z-10 bg-surface px-3 py-2.5 text-start text-micro font-semibold uppercase tracking-wider text-ink-dim ${className}`}
    >
      {children}
    </th>
  );
}

function Td({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return <td className={`px-3 py-2 text-ink-muted ${className}`}>{children}</td>;
}

/**
 * L'instant du franchissement d'un rôle — la cellule des colonnes « Entrée » et
 * « Sortie ».
 *
 * Au dixième de seconde (`formatSceneTimePrecise`), parce que deux passages du même
 * véhicule tombent régulièrement dans la même seconde et qu'un arrondi les rendrait
 * indistinguables.
 *
 * Quand un rôle porte plusieurs franchissements — aller-retour, deux lignes
 * d'entrée en travers de la même voie, piste coupée par une occlusion (invariant 6)
 * — la cellule montre le **premier** et annonce les autres par un « +N » : elle
 * n'en fusionne aucun, et l'infobulle les liste tous avec leur ligne. Prendre le
 * premier et taire le reste laisserait croire à un franchissement unique.
 *
 * `—` couvre **deux** cas que rien ne distingue ici, et c'est assumé : le véhicule
 * n'a rien franchi dans ce rôle, ou la ligne qu'il a franchie n'est plus dans le
 * tracé. Le second reste visible dans « Lignes franchies », qui affiche alors la
 * flèche brute — les inventer une heure serait pire.
 */
function RoleCrossingCell({
  vehicle,
  lines,
  role,
}: {
  vehicle: VehicleRecord;
  lines: readonly CountingLine[];
  role: DirectionRole;
}) {
  const crossings = crossingsWithRole(vehicle, lines, role);
  const first = crossings.at(0);

  if (first === undefined) {
    return (
      <Td>
        <span className="text-ink-dim">—</span>
      </Td>
    );
  }

  const others = crossings.length - 1;
  const title = crossings.map((crossing) => describeCrossing(lines, crossing)).join(" · ");

  return (
    <Td className="text-ink">
      {/* Une seule rangée : la flèche, le nom de la ligne tronqué, l'heure. Le
          `+N` compte les franchissements **suivants du même rôle** — un
          aller-retour, deux lignes d'entrée en travers de la même voie, une
          occlusion qui coupe la piste (invariant 6). Aucun n'est fusionné ni
          perdu : l'infobulle les porte tous. */}
      <span className="flex items-center gap-1.5" title={title}>
        <CrossingArrow lines={lines} lineId={first.lineId} direction={first.direction} />
        <span className="min-w-0 truncate">{lineName(lines, first.lineId)}</span>
        <span className="ms-auto shrink-0 text-micro text-ink-muted tabular">
          {formatSceneTimePrecise(first.timestampMs)}
        </span>
        {others > 0 && <span className="shrink-0 text-micro text-ink-dim">+{others}</span>}
      </span>
    </Td>
  );
}

/**
 * Les franchissements qu'**aucun rôle ne réclame** — ligne retirée du tracé, ou
 * sens resté neutre sur un tracé antérieur à ADR 0021.
 *
 * Rendus comme les anciennes puces de « Lignes franchies », flèche de repli
 * comprise : c'est exactement le cas que cette colonne couvrait, et que les deux
 * colonnes de rôle ne peuvent pas couvrir sans inventer un rôle. Les taire ferait
 * diverger le registre de la colonne « Passages », qui les compte.
 */
function UnroledCrossingCell({
  vehicle,
  lines,
}: {
  vehicle: VehicleRecord;
  lines: readonly CountingLine[];
}) {
  const crossings = crossingsWithoutRole(vehicle, lines);

  if (crossings.length === 0) {
    return (
      <Td>
        <span className="text-ink-dim">—</span>
      </Td>
    );
  }

  return (
    <Td className="text-ink-muted">
      <span className="flex flex-wrap gap-1">
        {crossings.map((crossing, index) => (
          <span
            key={`${crossing.lineId}-${crossing.timestampMs}-${index}`}
            title={describeCrossing(lines, crossing)}
            className="inline-flex items-center gap-1 rounded-badge bg-elevated px-1.5 py-0.5 text-micro"
          >
            <CrossingArrow lines={lines} lineId={crossing.lineId} direction={crossing.direction} />
            {lineName(lines, crossing.lineId)}
          </span>
        ))}
      </span>
    </Td>
  );
}

/**
 * La phrase d'infobulle d'un franchissement : la ligne, l'instant **et** le sens
 * nommé. C'est ce triplet qui permet de retrouver le passage dans la vidéo — le
 * nom du sens seul ne dit pas quand, l'heure seule ne dit pas par où.
 */
function describeCrossing(
  lines: readonly CountingLine[],
  crossing: VehicleRecord["crossedLines"][number],
): string {
  const way =
    crossingDirectionName(lines, crossing.lineId, crossing.direction) ??
    `sens ${directionArrow(crossing.direction)}`;
  return `${lineName(lines, crossing.lineId)} à ${formatSceneTimePrecise(crossing.timestampMs)}, ${way}`;
}
