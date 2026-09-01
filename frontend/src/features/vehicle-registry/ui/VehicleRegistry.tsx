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

import { ArrowUp, Ban, ImageOff, ShieldAlert } from "lucide-react";
import { useCallback, useDeferredValue, useEffect, useMemo, useRef, useState } from "react";

import { formatSceneTime, formatSceneTimePrecise } from "@/features/results-dashboard";
import type {
  AnalysisResult,
  CountingLine,
  DirectionRole,
  VehicleRecord,
} from "@/shared/api/contracts";
import { classColor } from "@/shared/config/palettes";
import { classLabel } from "@/shared/lib/classes";
// Le juge unique de la ressemblance : le tiroir d'alertes lit le même, donc un
// véhicule signalé là-bas est teinté ici, et réciproquement.
import { DEFAULT_REMATCH_THRESHOLD, matches, matchStrength } from "@/shared/lib/vehicleMatch";
import {
  crossingDirectionName,
  crossingHeadingDeg,
  directionArrow,
  lineName,
} from "@/shared/lib/directions";
import { platePhotoUrl, vehicleSnapshotUrl } from "@/shared/api/jobUrls";
import type { LineRule } from "@/shared/lib/lineRules";
import { plateCell, plateTitle } from "@/shared/lib/plate";
import { formatScore } from "@/shared/lib/score";
import { snapshotCaption } from "@/shared/lib/snapshotCaption";
import { snapshotHasPlateFace, snapshotReasonLabel } from "@/shared/lib/snapshotKind";
import { Button } from "@/shared/ui/Button";
import {
  SnapshotComparisonDialog,
  type ComparisonSide,
} from "@/shared/ui/SnapshotComparisonDialog";
import { SnapshotDialog } from "@/shared/ui/SnapshotDialog";

import {
  crossingsCsv,
  downloadText,
  exportFilename,
  resultJson,
  vehiclesCsv,
} from "../model/exportCsv";
import { filterByLine } from "../model/filterLine";
import { filterByPlate } from "../model/filterPlate";
import { plateBestGuessMessage, plateUnreadLabel, plateUnreadMessage } from "../model/plateUnread";
import { rematchPair } from "../model/rematchPair";
import { crossingsWithRole, crossingsWithoutRole } from "../model/roleCrossings";
import {
  capturedVehicles,
  hasSnapshot,
  hasSnapshots,
  neighbourVehicle,
  snapshotRowHeight,
} from "../model/snapshots";
import { vehicleViolations, type VehicleViolation } from "../model/vehicleViolations";
import { INITIAL_ROWS, shouldVirtualise, visibleWindow } from "../model/virtualise";

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
   * Seuil de ressemblance de la recherche par image, ou `null` — aucune recherche.
   *
   * Reçu en prop et non recalculé : `vehicle-registry` n'a pas le droit d'importer
   * `vehicle-search`, et surtout le registre doit teinter **exactement** ce que le
   * tiroir d'alertes signale. Deux seuils divergeraient sur un véhicule signalé
   * ailleurs et non teinté ici.
   */
  matchThreshold?: number | null;
  /**
   * La géométrie courante, pour nommer les lignes **et les sens**.
   *
   * Les lignes entières et non une `Map` de noms : une puce de franchissement affiche
   * désormais le nom du *sens*, que seule la ligne complète permet de calculer — le
   * défaut géométrique se déduit de `a` et `b`.
   */
  lines: readonly CountingLine[];
  /**
   * Les règles du tracé courant — sens interdits, voies réservées.
   *
   * Fournies par le studio et jamais recalculées ici : elles demandent le catalogue
   * de classes du serveur, que cette feature ne connaît pas. Une `Map` vide signifie
   * « aucune règle », et la colonne « Infraction » n'apparaît alors jamais.
   */
  rules: ReadonlyMap<string, LineRule>;
  /**
   * L'identifiant du job, pour construire les adresses des captures.
   *
   * **En cours ou terminé depuis ADR 0046.** Il ne valait que pour un job terminé
   * tant que les JPEG n'étaient écrits qu'à la fin : demander une vignette avant
   * aurait fait clignoter des images cassées sur tout le tableau. Ils sont
   * maintenant écrits au moment où la capture est retenue, donc la colonne peut se
   * remplir pendant l'analyse — au moment précis où l'on regarde le registre se
   * remplir.
   *
   * `null` avant toute analyse. Ce n'est **pas** la même chose que la règle des
   * trois boutons d'export, qui, eux, restent liés à `result` : un CSV incomplet
   * ment sur son contenu, une vignette manquante ne ment sur rien.
   */
  jobId: string | null;
  /**
   * L'analyse tourne-t-elle ?
   *
   * Ne change **aucun chiffre** et aucune colonne : sert uniquement à décider
   * qu'une capture absente mérite un second essai. Pendant l'analyse, le fichier
   * peut arriver quelques centaines de millisecondes après l'aperçu qui l'annonce ;
   * après, une image absente l'est pour de bon — c'est le cas normal une fois la
   * vidéo purgée — et réessayer doublerait des requêtes vouées à échouer.
   */
  live?: boolean;
}

/** Hauteur du conteneur virtualisé. */
const VIEWPORT_HEIGHT = 420;

export function VehicleRegistry({
  result,
  vehicles,
  lines,
  rules,
  jobId,
  live = false,
  matchThreshold = null,
}: VehicleRegistryProps) {
  const [expanded, setExpanded] = useState(false);
  //: Le véhicule dont la capture est ouverte en grand, ou `null`.
  const [openSnapshot, setOpenSnapshot] = useState<number | null>(null);
  /** Le véhicule dont on compare la re-détection, par son numéro. `null` = fermée. */
  const [openRematch, setOpenRematch] = useState<number | null>(null);
  const [scrollTop, setScrollTop] = useState(0);
  // L'état de recherche vit **ici**, comme `expanded` et `scrollTop` : c'est un état de
  // vue de ce tableau. Le hisser dans `StudioPage` ferait remonter chaque frappe dans le
  // composant qui rend aussi le canvas. La règle « le câblage passe par StudioPage »
  // vise les dépendances **entre features**, pas l'état interne d'un composant.
  const [plateQuery, setPlateQuery] = useState("");
  // Le champ répond au clavier, le tableau rattrape. Pas de debounce maison : React sait
  // déjà déprioriser ce rendu, et il n'existe aucun utilitaire de debounce dans ce dépôt.
  const deferredQuery = useDeferredValue(plateQuery);
  // Même nature que `plateQuery` : un état de vue de ce tableau. Les deux filtres se
  // composent — « les motos passées par la ligne 2 » est une question qu'on pose
  // d'un seul geste, pas deux.
  const [lineFilter, setLineFilter] = useState<string | null>(null);
  const scroller = useRef<HTMLDivElement>(null);

  const filtered = useMemo(
    () => filterByPlate(filterByLine(vehicles, lineFilter), deferredQuery),
    [vehicles, lineFilter, deferredQuery],
  );

  /**
   * Une infraction, **quelque part** dans le registre ?
   *
   * Sur `vehicles` et non sur les lignes rendues ni sur `filtered` : une colonne qui
   * apparaîtrait au défilement d'un tableau virtualisé — ou au changement d'un
   * filtre — décalerait toutes les autres sous le curseur. Elle existe pour tout le
   * tableau, ou pour aucun. Même raisonnement que `hasUnroled` juste dessous.
   */
  const hasViolation = useMemo(
    () => vehicles.some((entry) => vehicleViolations(entry, rules).length > 0),
    [vehicles, rules],
  );

  /**
   * Une ressemblance est-elle mesurée **quelque part** dans ce registre ?
   *
   * Décidée sur `vehicles` entier et jamais sur les rangées rendues ni sur le jeu
   * filtré, même règle que « Capture » : une colonne qui apparaîtrait au défilement
   * décalerait toutes les autres sous le curseur.
   *
   * Sans recherche armée, aucun véhicule ne porte de `matchScore` — la colonne est
   * donc absente sans qu'aucun réglage n'ait à le dire.
   */
  const hasMatch = useMemo(
    () =>
      matchThreshold !== null &&
      vehicles.some((entry) => entry.matchScore !== null && entry.matchScore !== undefined),
    [vehicles, matchThreshold],
  );

  /**
   * Un véhicule a-t-il été **re-détecté** quelque part dans ce registre (ADR 0055) ?
   *
   * Même règle et même raison que `hasMatch` juste au-dessus : décidé sur `vehicles`
   * entier, jamais sur les rangées rendues.
   *
   * **Sans seuil dans la condition**, contrairement à `hasMatch` : `rematchOf` n'est
   * publié que si le serveur a trouvé quelque chose, donc sa seule présence dit que
   * la fonctionnalité a tourné. La colonne montre alors aussi les scores sous le
   * curseur, en gris — c'est ce qui permet de voir qu'on est passé à côté de peu.
   */
  const hasRematch = useMemo(
    () => vehicles.some((entry) => entry.rematchOf !== null && entry.rematchOf !== undefined),
    [vehicles],
  );

  /**
   * Une capture existe-t-elle **quelque part** dans ce registre ?
   *
   * Même règle et même raison que les deux drapeaux ci-dessus : calculé sur
   * `vehicles` entier, jamais sur `filtered` ni sur les rangées rendues.
   *
   * `jobId` le conditionne parce que les fichiers ne sont écrits qu'à la fin de
   * l'analyse : pendant, les enregistrements de l'aperçu portent déjà un score de
   * capture, mais l'image n'existe pas encore.
   */
  const withSnapshots = jobId !== null && hasSnapshots(vehicles);
  // La virtualisation calcule ses décalages depuis cette hauteur : elle doit être la
  // **même** que celle posée en style sur `<tr>`, sinon les rangées dérivent sous le
  // curseur au-delà de 200 lignes.
  const rowHeight = snapshotRowHeight(withSnapshots);

  /**
   * Les captures entre lesquelles la modale navigue, et celle qui est ouverte.
   *
   * Sur `filtered` et non sur `vehicles` : après avoir filtré sur une ligne ou sur
   * une plaque, « suivant » doit rester dans ce qu'on regarde. Sortir du filtre
   * donnerait l'impression que le tableau ment.
   */
  const navigable = useMemo(() => capturedVehicles(filtered), [filtered]);
  const shownSnapshot =
    openSnapshot === null
      ? null
      : (navigable.find((entry) => entry.globalId === openSnapshot) ?? null);
  const previousSnapshot =
    shownSnapshot === null ? null : neighbourVehicle(navigable, shownSnapshot.globalId, -1);
  const nextSnapshot =
    shownSnapshot === null ? null : neighbourVehicle(navigable, shownSnapshot.globalId, 1);

  // Sur `vehicles` et **jamais sur `filtered`** : l'antécédent peut être masqué par
  // le filtre courant, et le taire viderait la comparaison de son sens précisément
  // quand on en a besoin. `rematchPair` en est le seul juge, et il est testé.
  const comparison = openRematch === null ? null : rematchPair(vehicles, openRematch);

  const virtualised = expanded && shouldVirtualise(filtered.length);
  const shown = expanded ? filtered : filtered.slice(0, INITIAL_ROWS);
  const remaining = filtered.length - shown.length;

  const window = useMemo(
    () =>
      virtualised
        ? visibleWindow(filtered.length, scrollTop, VIEWPORT_HEIGHT, rowHeight)
        : { start: 0, end: shown.length, totalHeight: 0, offsetTop: 0 },
    [virtualised, filtered.length, scrollTop, shown.length, rowHeight],
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

  // Remise à zéro du défilement quand **l'un des deux filtres** change : sinon
  // `visibleWindow` calcule une fenêtre au-delà de la fin d'un jeu réduit, et le
  // tableau **paraît vide** alors qu'il contient des lignes. Le filtre par ligne y
  // est aussi exposé que la recherche, et davantage : il peut faire passer un
  // registre de 4 000 lignes à 12 d'un seul clic.
  useEffect(() => {
    setScrollTop(0);
    if (scroller.current !== null) scroller.current.scrollTop = 0;
  }, [deferredQuery, lineFilter]);

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
          {/* N'existe que si une ligne du tableau en porte : un franchissement
              qu'aucune colonne ne réclame — ligne retirée du tracé, sens resté
              neutre sur un tracé antérieur à ADR 0021, ou ligne en « comptage seul »,
              qui compte sans rien classer. Le ranger sous un rôle serait une
              invention ; le taire ferait diverger le registre de la colonne
              « Passages », qui le compte.

              **« Autres passages » et non « Hors rôle »** depuis que `transit`
              existe : ce dernier *a* un rôle, délibérément choisi, et le dire « hors
              rôle » se lirait comme un oubli de l'utilisateur. */}
          {hasUnroled && <Th className="w-40">Autres passages</Th>}
          {/* N'existe que si une ligne du tableau en porte, et le calcul se fait sur
              le registre **entier** : une colonne qui apparaîtrait au défilement ou
              au changement d'un filtre décalerait toutes les autres sous le curseur.

              Un seul nom — « Infraction » — et non « Sens interdit », qui deviendrait
              faux dès qu'une voie réservée existe. Deux noms pour une colonne, c'est
              deux colonnes dans la tête du lecteur. */}
          {hasViolation && <Th className="w-44">Infraction</Th>}
          {/* La photo juste avant le texte qu'elle prouve : l'une se lit contre
              l'autre, et les séparer obligerait à recoller deux colonnes du regard.

              Conditionnelle et calculée sur le registre **entier** — jamais sur les
              rangées rendues ni sur le jeu filtré, sinon la colonne apparaîtrait au
              défilement et décalerait toutes les autres sous le curseur. */}
          {withSnapshots && <Th className="w-16">Capture</Th>}
          {/* « Ressemblance » juste après la capture, et pour la même raison qui met
              la capture avant la plaque : le score se vérifie **sur la photo**, et
              les séparer obligerait à recoller deux colonnes du regard. */}
          {hasMatch && <Th className="w-24">Ressemblance</Th>}
          {/* « Déjà vu » à côté de « Ressemblance » : les deux sont des similarités
              d'apparence et se lisent ensemble. Elles ne disent pourtant pas la même
              chose — l'une compare à une photo fournie, l'autre aux véhicules déjà
              passés — d'où deux colonnes et non une. */}
          {hasRematch && <Th className="w-28">Déjà vu</Th>}
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
            style={{ height: rowHeight }}
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
            {hasViolation && <ViolationCell vehicle={vehicle} rules={rules} />}
            {withSnapshots && (
              <SnapshotCell
                live={live}
                vehicle={vehicle}
                jobId={jobId}
                onOpen={() => setOpenSnapshot(vehicle.globalId)}
              />
            )}
            {hasMatch && <MatchCell vehicle={vehicle} threshold={matchThreshold} />}
            {hasRematch && (
              <RematchCell
                vehicle={vehicle}
                // Sans job, aucune image n'existe : la cellule reste du texte plutôt
                // qu'un bouton qui n'ouvrirait qu'une modale de deux repères muets.
                onCompare={
                  jobId === null ? undefined : () => setOpenRematch(vehicle.globalId)
                }
              />
            )}
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
          {/* Juste à côté de la recherche, parce que les deux répondent à la même
              question posée autrement : « lequel ». Les noms viennent du tracé
              **courant** — renommer une ligne renomme l'option sans réanalyser, comme
              partout ailleurs dans cette interface.

              Masqué s'il n'y a qu'une ligne : un menu à un seul choix n'en est pas
              un, et il occuperait la place du champ voisin sur une fenêtre étroite. */}
          {lines.length > 1 && (
            <label className="flex items-center gap-2">
              <span className="sr-only">Filtrer par ligne franchie</span>
              <select
                value={lineFilter ?? ""}
                onChange={(event) => setLineFilter(event.target.value || null)}
                title="N'afficher que les véhicules ayant franchi cette ligne, dans un sens ou dans l'autre"
                className="max-w-44 rounded-input bg-elevated px-3 py-1.5 text-small text-ink"
              >
                <option value="">Toutes les lignes</option>
                {lines.map((line) => (
                  <option key={line.id} value={line.id}>
                    {line.name}
                  </option>
                ))}
              </select>
            </label>
          )}
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
          {/* Le vide **nomme le filtre qui l'a produit** : avec deux filtres qui se
              composent, « aucune plaque ne contient X » enverrait corriger la
              recherche alors que c'est la ligne choisie qui ne porte rien. */}
          {emptyReason(plateQuery, lineFilter, lines)}{" "}
          <button
            type="button"
            onClick={() => {
              setPlateQuery("");
              setLineFilter(null);
            }}
            className="underline transition-colors hover:text-ink"
          >
            Réinitialiser les filtres
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

      {/* Montée seulement une fois ouverte : un `<dialog>` fermé n'a rien à rendre,
          et surtout ses deux `<img>` ne doivent pas se charger tant que personne ne
          les regarde — ce serait deux requêtes de plus par ligne du tableau, ce que
          `loading="lazy"` sur la vignette existe justement pour éviter. */}
      {jobId !== null && shownSnapshot !== null && (
        <SnapshotDialog
          open
          onClose={() => setOpenSnapshot(null)}
          title={`${classLabel(shownSnapshot.label)} #${shownSnapshot.globalId}`}
          subtitle={snapshotCaption(shownSnapshot, formatSceneTimePrecise)}
          vehicleSrc={vehicleSnapshotUrl(jobId, shownSnapshot.globalId, shownSnapshot.snapshotMs)}
          // **Demandée seulement si elle existe.** Une capture retenue pour la
          // ressemblance du véhicule n'a pas de plaque : la demander rendrait 409, et
          // la modale afficherait « Capture purgée » sur un état parfaitement normal.
          plateSrc={
            snapshotHasPlateFace(shownSnapshot.snapshotKind)
              ? platePhotoUrl(jobId, shownSnapshot.globalId, shownSnapshot.snapshotMs)
              : null
          }
          plateText={shownSnapshot.plateText}
          // La navigation porte sur les véhicules **affichés**, filtres compris :
          // après avoir filtré sur une ligne, « suivant » doit rester dans ce qu'on
          // regarde.
          onPrevious={previousSnapshot === null ? undefined : () => setOpenSnapshot(previousSnapshot.globalId)}
          onNext={nextSnapshot === null ? undefined : () => setOpenSnapshot(nextSnapshot.globalId)}
        />
      )}

      {/* La comparaison d'une re-détection. Montée seulement une fois ouverte, comme
          la modale de capture, et pour la même raison : ses quatre `<img>` ne doivent
          pas se charger tant que personne ne les regarde. */}
      {jobId !== null && comparison !== null && (
        <SnapshotComparisonDialog
          open
          onClose={() => setOpenRematch(null)}
          title="Ce véhicule est-il déjà passé ?"
          score={
            comparison.later.rematchScore == null
              ? undefined
              : formatScore(comparison.later.rematchScore)
          }
          earlier={comparisonSide(jobId, comparison.earlier)}
          later={comparisonSide(jobId, comparison.later)}
        />
      )}
    </section>
  );
}

/**
 * Un véhicule vu comme une colonne de la comparaison.
 *
 * La vignette de plaque n'est demandée que si elle **existe** — une capture retenue
 * pour la ressemblance du véhicule n'en a aucune (ADR 0051), et la demander rendrait
 * 409, donc le repère « Capture purgée » sur un état parfaitement normal. Même garde
 * qu'à la modale de capture, par le même juge.
 */
function comparisonSide(jobId: string, vehicle: VehicleRecord): ComparisonSide {
  return {
    title: `${classLabel(vehicle.label)} #${vehicle.globalId}`,
    subtitle: snapshotCaption(vehicle, formatSceneTimePrecise),
    vehicleSrc: vehicleSnapshotUrl(jobId, vehicle.globalId, vehicle.snapshotMs),
    plateSrc: snapshotHasPlateFace(vehicle.snapshotKind)
      ? platePhotoUrl(jobId, vehicle.globalId, vehicle.snapshotMs)
      : null,
    plateText: vehicle.plateText,
  };
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

/**
 * Pourquoi le tableau est vide, en nommant **le** filtre en cause.
 *
 * Deux filtres qui se composent produisent trois vides distincts, et les confondre
 * envoie corriger le mauvais : « aucune plaque ne contient 2418 » sur un registre
 * dont la ligne choisie n'a jamais rien compté fait chercher une faute de frappe
 * pendant que le menu voisin porte la cause.
 */
function emptyReason(
  plateQuery: string,
  lineFilter: string | null,
  lines: readonly CountingLine[],
): string {
  const searching = plateQuery.trim() !== "";
  const named = lineFilter === null ? null : lineName(lines, lineFilter);
  if (searching && named !== null) {
    return `Aucun véhicule passé par ${named} ne porte une plaque contenant « ${plateQuery} ».`;
  }
  if (named !== null) return `Aucun véhicule n'a franchi ${named}.`;
  return `Aucune plaque ne contient « ${plateQuery} ».`;
}

/**
 * Les infractions d'un véhicule, une pastille par fait.
 *
 * Une seule rangée par cellule, comme ses voisines : empiler casserait `ROW_HEIGHT`,
 * dont dépend la virtualisation au-delà de 200 lignes. Au-delà de la première, les
 * suivantes sont **annoncées** par « +N » et jamais fusionnées — deux infractions du
 * même véhicule sont deux faits, pas un doublon d'affichage.
 */
function ViolationCell({
  vehicle,
  rules,
}: {
  vehicle: VehicleRecord;
  rules: ReadonlyMap<string, LineRule>;
}) {
  const found = vehicleViolations(vehicle, rules);
  if (found.length === 0) return <Td className="text-ink-dim">—</Td>;

  const [first, ...rest] = found as [VehicleViolation, ...VehicleViolation[]];
  const Icon = first.kind === "reserved-lane" ? ShieldAlert : Ban;

  return (
    <Td>
      <span
        className="flex min-w-0 items-center gap-1"
        title={found
          .map((entry) => `${violationWord(entry.kind)} — ${entry.lineName}`)
          .join("\n")}
      >
        <Icon aria-hidden="true" className="size-3 shrink-0 text-negative" />
        <span className="min-w-0 truncate font-bold text-negative">
          {violationWord(first.kind)}
        </span>
        <span className="min-w-0 truncate text-ink-dim">{first.lineName}</span>
        {rest.length > 0 && <span className="shrink-0 text-ink-dim">+{rest.length}</span>}
      </span>
    </Td>
  );
}

/** Le mot d'une infraction. Court : la cellule fait `w-44` et porte déjà un nom de ligne. */
function violationWord(kind: VehicleViolation["kind"]): string {
  if (kind === "reserved-lane") return "Voie réservée";
  if (kind === "closed-line") return "Infranchissable";
  return "Sens interdit";
}

/**
 * La vignette du véhicule, cliquable.
 *
 * `loading="lazy"` **est** toute l'histoire de performance côté client : seules les
 * rangées visibles demandent leur image, ce qui rend un registre de deux cents lignes
 * aussi léger qu'un registre de douze. Sans lui, ouvrir le tableau déclencherait deux
 * cents requêtes d'un coup — et la limite de débit du serveur exempte justement les
 * lectures de job pour que ce cas reste possible.
 *
 * Dimensions posées en attributs **et** en classes : l'attribut réserve la place
 * avant que l'image arrive, ce qui évite que la rangée saute à son chargement.
 */
/**
 * La ressemblance à l'image de requête — un pourcentage, teinté par sa gravité.
 *
 * **Le score est affiché, pas seulement la couleur.** Contrairement à une carte
 * d'alerte, où « 0,63 » ne se lit pas d'un coup d'œil dans une pile, le registre est
 * un tableau qu'on parcourt colonne par colonne : c'est exactement le lieu où
 * comparer deux scores entre eux a du sens, et où le classement se lit.
 *
 * Le seuil vient en prop pour que le mot « ressemble » veuille dire la même chose ici
 * et dans le tiroir d'alertes. `matchStrength` en est le seul juge.
 */
function MatchCell({
  vehicle,
  threshold,
}: {
  vehicle: VehicleRecord;
  threshold: number | null;
}) {
  const score = vehicle.matchScore;
  if (score === null || score === undefined) {
    // Deux causes, un seul rendu : jamais encodé — trop petit ou trop flou, le cas le
    // plus courant sur une vue large — ou pas de requête. L'écran n'a pas à les
    // distinguer, il n'y a rien à classer dans les deux cas.
    return <Td className="w-24 text-ink-muted">—</Td>;
  }
  const strength = threshold === null ? null : matchStrength(score, threshold);
  const under = !matches(score, threshold);
  return (
    <Td
      className={`w-24 tabular ${
        under
          ? "text-ink-muted"
          : strength === "exact"
            ? "font-medium text-negative"
            : "text-warning"
      }`}
    >
      {/* Le score brut en infobulle sur le texte, `Td` n'acceptant pas de `title` : le
          pourcentage arrondi suffit à comparer deux rangées, mais pas à comprendre
          pourquoi un véhicule tombe juste sous le curseur. */}
      <span title={`Similarité ${score.toFixed(3)}${under ? " — sous le seuil retenu" : ""}`}>
        {`${Math.round(score * 100)} %`}
      </span>
    </Td>
  );
}

/**
 * « Ce véhicule est déjà passé » — l'antécédent et la ressemblance (ADR 0055).
 *
 * **Le numéro et le pourcentage ensemble, jamais l'un sans l'autre.** « 87 % » seul
 * ne se vérifie sur rien ; « comme #12 » seul cache que ce n'est qu'une hypothèse.
 * C'est la même raison qui met la capture à côté de la ressemblance.
 *
 * Le seuil ne vient **pas** en prop, contrairement à `MatchCell` : la colonne
 * n'existe que si le serveur a trouvé quelque chose, et le curseur d'affichage ne
 * décide ici que d'une teinte. Un score sous le seuil reste lisible en gris — c'est
 * ce qui permet de voir qu'on est passé à côté de peu, et de descendre le seuil en
 * connaissance de cause.
 */
function RematchCell({
  vehicle,
  onCompare,
}: {
  vehicle: VehicleRecord;
  onCompare?: (() => void) | undefined;
}) {
  const { rematchOf, rematchScore } = vehicle;
  if (rematchOf === null || rematchOf === undefined) {
    return <Td className="w-28 text-ink-muted">—</Td>;
  }
  const under = !matches(rematchScore, DEFAULT_REMATCH_THRESHOLD);
  const strength =
    rematchScore == null ? null : matchStrength(rematchScore, DEFAULT_REMATCH_THRESHOLD);
  const ink = under
    ? "text-ink-muted"
    : strength === "exact"
      ? "font-medium text-negative"
      : "text-warning";
  const label =
    rematchScore == null ? `#${rematchOf}` : `#${rematchOf} — ${Math.round(rematchScore * 100)} %`;
  const detail =
    rematchScore == null
      ? `Ressemble au véhicule #${rematchOf}`
      : `Similarité ${rematchScore.toFixed(3)} avec le véhicule #${rematchOf}${
          under ? " — sous le seuil retenu" : ""
        }`;

  // **Cliquable, et c'est ce qui rend l'affirmation vérifiable.** Le score dit « ces
  // deux véhicules se ressemblent » ; seule la comparaison des deux photos permet de
  // le confirmer ou de le réfuter, et l'écran le promet en toutes lettres. Sans job,
  // aucune image n'existe : la cellule reste alors du texte, pas un bouton mort.
  if (onCompare === undefined) {
    return (
      <Td className={`w-28 tabular ${ink}`}>
        <span title={detail}>{label}</span>
      </Td>
    );
  }
  // Un `<td>` nu et non le `Td` partagé, pour la même raison que la cellule de
  // capture : `Td` porte `px-3 py-2`, et une surcharge `p-0` ne gagne pas de façon
  // fiable — l'ordre des utilitaires de rembourrage dans la feuille générée décide,
  // pas l'ordre des classes. Le rembourrage passe donc sur le bouton, qui doit le
  // porter de toute façon pour que toute la cellule soit cliquable. Les valeurs sont
  // identiques à celles de `Td`, sans quoi la rangée changerait de hauteur et la
  // virtualisation dériverait au-delà de 200 lignes.
  return (
    <td className="w-28 text-ink-muted">
      <button
        type="button"
        onClick={onCompare}
        title={`${detail} — cliquer pour comparer les deux photos`}
        className={`w-full px-3 py-2 text-start tabular underline decoration-dotted underline-offset-2 transition-colors hover:bg-elevated ${ink}`}
      >
        {label}
      </button>
    </td>
  );
}

function SnapshotCell({
  vehicle,
  jobId,
  live,
  onOpen,
}: {
  vehicle: VehicleRecord;
  jobId: string;
  /** L'analyse tourne : une capture absente peut n'être qu'en retard. */
  live: boolean;
  onOpen: () => void;
}) {
  const [attempt, setAttempt] = useState(0);
  const [failed, setFailed] = useState(false);

  if (!hasSnapshot(vehicle)) return <Td className="text-ink-dim">—</Td>;

  if (failed) {
    // Deux causes, un seul repère, et c'est délibéré : purgée avec la vidéo après le
    // TTL, ou — pendant l'analyse et après un réessai — pas encore écrite. Les deux
    // sont le cas **normal** et aucune n'est une panne ; un repère muet le dit mieux
    // que l'image cassée du navigateur, et distinguer les deux demanderait à
    // l'utilisateur de comprendre un détail d'implémentation pour lire un tableau.
    return (
      <Td>
        <span title="Capture indisponible — pas encore écrite, ou effacée en même temps que la vidéo.">
          <ImageOff aria-hidden="true" className="size-4 text-ink-dim" />
        </span>
      </Td>
    );
  }

  return (
    // **Son propre `<td>` et pas le `Td` partagé, à cause d'une seule chose : le
    // rembourrage vertical.** `Td` dépense `py-2`, ce qui ajoute 16 px à une vignette
    // de 40 et pousse la rangée à 57 px — alors que la virtualisation en calcule 48.
    // Les rangées dérivent alors sous le curseur, et seulement au-delà de 200 lignes,
    // donc jamais sur un jeu de test à la main.
    //
    // Le `height` d'une rangée n'est qu'un **minimum** en CSS : le contenu doit tenir
    // dessous, il ne suffit pas de le déclarer. D'où `py-0` ici, qui laisse 8 px de
    // marge sous les 48.
    <td className="px-3 py-0 align-middle">
      <button
        type="button"
        onClick={onOpen}
        // **Pourquoi** cette photo existe, dans l'infobulle : sans elle, une photo
        // sans plaque lue se lirait comme une lecture perdue.
        title={`Voir la capture du véhicule #${vehicle.globalId} — ${snapshotReasonLabel(vehicle.snapshotKind)}`}
        className="block overflow-hidden rounded-input ring-1 ring-line/40 transition-transform hover:scale-105"
      >
        <img
          // **Deux paramètres, deux rôles.** `snapshotMs` versionne la capture : le
          // serveur sert ces images en `immutable`, et une meilleure lecture
          // remplace le fichier en cours d'analyse — sans version, le navigateur
          // garderait la première pour un an. `retry` casse en plus le cache
          // d'échec, sans quoi un second chargement de la même adresse
          // ressusciterait la réponse en erreur au lieu de redemander.
          // La composition de la requête vit dans `jobUrls` : elle était écrite ici
          // en supposant `?v=` présent, et dans la pile d'alertes en supposant
          // l'inverse — deux appelants qui devinaient la ponctuation l'un de l'autre.
          src={vehicleSnapshotUrl(jobId, vehicle.globalId, vehicle.snapshotMs, attempt)}
          alt={`Capture du véhicule #${vehicle.globalId}`}
          width={40}
          height={40}
          loading="lazy"
          decoding="async"
          // `cover` ici et `contain` dans la modale : la vignette est un repère, on
          // accepte qu'elle rogne ; la grande image est une preuve, on ne la rogne
          // jamais.
          className="block size-10 bg-base object-cover"
          // **Un seul réessai, et seulement pendant l'analyse.** Le fichier est
          // écrit au moment de la capture mais l'aperçu qui l'annonce arrive par un
          // autre chemin : quelques centaines de millisecondes peuvent les séparer.
          // Après l'analyse, une image absente l'est pour de bon, et réessayer
          // doublerait des requêtes vouées à échouer sur chaque rangée visible.
          onError={() => {
            if (live && attempt === 0) setAttempt(1);
            else setFailed(true);
          }}
        />
      </button>
    </td>
  );
}
