/**
 * Statistique — le tableau de bord du carrefour, ligne par ligne.
 *
 * Remplace l'ancien onglet « Par ligne & sens » (et sa matrice « Mouvements »,
 * retirée sans reconstruction) par une lecture **compacte, jamais en
 * accordéon** : tout est visible sans dépli. Trois étages —
 *
 * 1. un chiffre de tête, le total de véhicules ayant emprunté le carrefour ;
 * 2. une rangée compacte par ligne : nom, entrées/sorties/solde/part et une
 *    barre bidirectionnelle **unique** (un segment entrée, un segment sortie,
 *    côte à côte plutôt qu'empilés sur deux lignes) — **paginée** au-delà de
 *    `LINES_PER_PAGE`, voir plus bas ;
 * 3. des comparatifs entre lignes (`highlights.ts`), regroupés dans **une
 *    seule carte** plutôt qu'une par comparatif — six `MetricCard` à 1,75 rem
 *    de chiffre et `p-4` de marge pour une phrase chacune laissaient la moitié
 *    de la section en vide.
 *
 * L'occupation de zone (présente dans l'ancien onglet) **n'a pas d'équivalent
 * ici** — décision assumée : ce tableau de bord ne parle que de lignes.
 */

import { ChevronLeft, ChevronRight } from "lucide-react";
import { useState, type ReactNode } from "react";

import type { AnalysisStats, CountingLine, VehicleRecord } from "@/shared/api/contracts";

import { enteringVehicleCount } from "../model/crossedVehicles";
import {
  busiestLine,
  busiestVsQuietestShareGap,
  mostEnteredLine,
  mostExitedLine,
  mostForbiddenLine,
  quietestLine,
  strongestInflowLine,
  strongestOutflowLine,
  type LineHighlight,
} from "../model/highlights";
import { crossroadFlowSentence } from "../model/labels";
import { lineFlows } from "../model/lineFlows";
import { pageWindow } from "../model/paging";
import { EntryExitBar } from "./EntryExitBar";

/**
 * Rangées de lignes par page.
 *
 * Six et non dix : la section est **sous** la vidéo, donc ce qu'on en voit sans
 * défiler est une bande de quelques rangées, et la carte de comparatifs qui la suit
 * doit rester atteignable. Au-delà, la liste devenait le plus long bloc de la page
 * pour la partie la moins consultée — les comparatifs répondent déjà à « quelle
 * ligne » sans lire les rangées une à une.
 */
const LINES_PER_PAGE = 6;

interface LineFlowDashboardProps {
  stats: AnalysisStats;
  lines: readonly CountingLine[];
  /**
   * Les véhicules visibles à la tête de lecture — **déjà filtrés** sur « a
   * franchi au moins une ligne » par l'appelant, comme le registre.
   *
   * Le chiffre de tête en dérive plutôt que de lire `stats.trackedVehicles` :
   * ce dernier compte tout objet suivi confirmé, stationnement compris, et
   * affichait 106 sous 28 entrées sur la même analyse.
   */
  vehicles: readonly VehicleRecord[];
}

/**
 * Un comparatif de la carte du bas : son libellé, sa ligne gagnante et sa
 * justification.
 *
 * **La justification est découpée pour que son chiffre puisse ressortir.** Elle
 * était une phrase d'un seul tenant, rendue entièrement en `text-ink-dim` : le
 * seul élément en pleine encre était le *nom* de la ligne, si bien que « 3
 * entrées » ou « Solde +2 » — la mesure qui justifie la sélection — se lisait au
 * même niveau que le texte d'explication autour.
 *
 * Le découpage reste des chaînes et non du JSX : la donnée d'un comparatif doit
 * rester testable et traduisible sans passer par un rendu.
 */
interface HighlightItem {
  label: string;
  highlight: LineHighlight | null;
  /** Ce qui précède le chiffre — « Solde », ou rien. */
  lead?: string;
  /** Le chiffre qui justifie la sélection, rendu en pleine encre et en gras. */
  metric: (h: LineHighlight) => string;
  /** L'unité puis l'explication, en second plan. Commence par son espace. */
  trail: string;
}

export function LineFlowDashboard({ stats, lines, vehicles }: LineFlowDashboardProps) {
  // **Avant le retour anticipé** : un hook ne peut pas vivre après un `return`
  // conditionnel, et l'ordre des hooks est ce que React vérifie à chaque rendu.
  const [requestedPage, setRequestedPage] = useState(0);

  // La page est **bornée à la lecture** et non corrigée par un effet : retirer
  // trois lignes du tracé pendant qu'on lit la dernière page laisserait sinon une
  // liste vide sous une pagination qui annonce des rangées, le temps d'un rendu.
  // `pageWindow` est testé pour ce cas précis.
  const view = pageWindow(lines.length, LINES_PER_PAGE, requestedPage);
  const pageLines = lines.slice(view.start, view.end);

  if (lines.length === 0) return null;

  const entered = enteringVehicleCount(vehicles, lines);

  const busiest = busiestLine(stats, lines);
  // Nommer la ligne la moins fréquentée n'a de sens qu'à partir de deux lignes :
  // sur un tracé unique, la plus et la moins fréquentée sont la même, et
  // l'afficher deux fois se lit comme un défaut d'affichage.
  const quietest = lines.length > 1 ? quietestLine(stats, lines) : null;
  const mostEntered = mostEnteredLine(stats, lines);
  const mostExited = mostExitedLine(stats, lines);
  const inflow = strongestInflowLine(stats, lines);
  const outflow = strongestOutflowLine(stats, lines);
  const mostForbidden = mostForbiddenLine(stats, lines);
  const gap = busiestVsQuietestShareGap(stats, lines);

  // **Les comparatifs vont par paires**, et la mise en page le dit : chaque
  // colonne porte une question et sa réciproque, l'une au-dessus de l'autre —
  // entrées/sorties, afflux/reflux, la plus/la moins fréquentée — puis l'écart
  // seul à droite. Une grille à plat les rangeait par ordre d'arrivée, et un
  // comparatif se lit contre son pendant, jamais isolément.
  //
  // Le regroupement en colonnes est aussi ce qui rend le filtrage sûr : un
  // comparatif absent (aucun rôle déclaré, aucun passage) laisse sa moitié de
  // colonne vide sans décaler ceux des autres paires, ce qu'un simple
  // `filter` sur une liste à plat ferait.
  const highlightPairs: HighlightItem[][] = [
    [
      {
        label: "Plus d'entrées",
        highlight: mostEntered !== null && mostEntered.value > 0 ? mostEntered : null,
        metric: (h) => String(h.value),
        trail: " entrées — la plus empruntée pour entrer",
      },
      {
        label: "Plus de sorties",
        highlight: mostExited !== null && mostExited.value > 0 ? mostExited : null,
        metric: (h) => String(h.value),
        trail: " sorties — la plus empruntée pour sortir",
      },
    ],
    [
      {
        label: "Plus fort afflux",
        highlight: inflow !== null && inflow.value > 0 ? inflow : null,
        lead: "Solde ",
        metric: (h) => `+${h.value}`,
        trail: " — le carrefour s'y remplit le plus",
      },
      {
        label: "Plus fort reflux",
        highlight: outflow !== null && outflow.value > 0 ? outflow : null,
        lead: "Solde ",
        // `value` vaut `-net`, donc un nombre positif : le signe est écrit ici.
        metric: (h) => `-${h.value}`,
        trail: " — le carrefour s'y vide le plus",
      },
      // **Le seul comparatif qui désigne un endroit plutôt qu'un flux.** Il répond
      // à « où faut-il aller voir » : une ligne à sens unique que dix véhicules
      // remontent est un problème de terrain — un panneau invisible, un marquage
      // effacé — et c'est la ligne, pas le total, qui le dit. Absent tant que rien
      // n'a été enfreint : ce comparatif ne se lit qu'avec un chiffre.
      {
        label: "Plus de contresens",
        highlight: mostForbidden !== null && mostForbidden.value > 0 ? mostForbidden : null,
        metric: (h) => String(h.value),
        trail: " passages interdits — la ligne à surveiller",
      },
    ],
    [
      {
        label: "Ligne la plus fréquentée",
        highlight: busiest,
        metric: (h) => String(h.value),
        trail: " passages, tous sens confondus",
      },
      {
        label: "Ligne la moins fréquentée",
        highlight: quietest,
        metric: (h) => String(h.value),
        trail: " passages, tous sens confondus",
      },
    ],
  ];
  const shownColumns = highlightPairs
    .map((column) => column.filter((item) => item.highlight !== null))
    .filter((column) => column.length > 0);

  return (
    <section aria-labelledby="statistique-title" className="space-y-3">
      <h2 id="statistique-title" className="label-micro">
        Statistique
      </h2>

      {/* **Des véhicules distincts entrés, pas des passages.** Un véhicule qui
          entre deux fois compte 1 ici et 2 dans les passages de sa ligne : deux
          questions, deux unités, et on ne les divise jamais l'une par l'autre
          (invariant 3). */}
      <div className="flex flex-wrap items-baseline justify-between gap-2 rounded-card bg-surface p-3 shadow-card">
        <span className="min-w-0">
          <span className="label-micro block">Véhicules ayant traversé le carrefour</span>
          <span className="text-micro text-ink-dim">
            Entrés par une ligne — le stationnement et les sorties seules sont exclus
          </span>
        </span>
        <span className="text-[1.75rem] font-bold leading-tight text-ink tabular">{entered}</span>
      </div>

      {/* La liste des lignes, **paginée** au-delà de six rangées. Trois points qui
          ne se devinent pas :

          - **la pagination n'existe que si elle sert** (`view.paginated`) : des
            commandes sous une liste de deux rangées sont du bruit, et elles
            annonceraient un découpage que personne n'a subi ;
          - **l'ordre est celui du tracé**, jamais un tri par fréquentation. La
            pastille de couleur relie chaque rangée à un trait sur la vidéo : un
            ordre qui change quand les chiffres changent — et ils changent à chaque
            image pendant l'analyse — ferait sauter les rangées sous le curseur. Le
            classement par valeur existe, il est dans les camemberts et les
            comparatifs, là où il ne coûte pas ce repère ;
          - **le rang de chaque ligne est écrit** (`view.start + index`) : sans lui,
            deux pages de rangées identiques en tout point sauf les chiffres ne
            disent pas laquelle on regarde. */}
      <div className="overflow-hidden rounded-card bg-surface shadow-card">
        <ul>
          {pageLines.map((line, index) => (
            <LineFlowRow
              key={line.id}
              stats={stats}
              line={line}
              rank={view.start + index + 1}
              bordered={index > 0}
            />
          ))}
        </ul>

        {view.paginated && (
          <nav
            aria-label="Pagination des lignes"
            className="flex items-center justify-between gap-2 border-t border-line/40 px-3 py-2"
          >
            {/* Le décompte d'abord : c'est lui qui dit qu'il y a une suite, et le
                seul élément utile quand les deux boutons sont grisés. */}
            <p className="text-micro text-ink-dim tabular">
              Lignes <span className="font-bold text-ink">{view.start + 1}</span>–
              <span className="font-bold text-ink">{view.end}</span> sur {lines.length}
            </p>

            <div className="flex items-center gap-1">
              <PageButton
                label="Page précédente"
                disabled={view.page === 0}
                onClick={() => setRequestedPage(view.page - 1)}
              >
                <ChevronLeft aria-hidden="true" className="size-4" />
              </PageButton>
              <p className="px-1 text-micro text-ink-muted tabular">
                {view.page + 1} / {view.pageCount}
              </p>
              <PageButton
                label="Page suivante"
                disabled={view.page >= view.pageCount - 1}
                onClick={() => setRequestedPage(view.page + 1)}
              >
                <ChevronRight aria-hidden="true" className="size-4" />
              </PageButton>
            </div>
          </nav>
        )}
      </div>

      {(shownColumns.length > 0 || gap !== null) && (
        <div className="grid grid-cols-1 gap-x-4 gap-y-3 rounded-card bg-surface p-3 shadow-card sm:grid-cols-2 lg:grid-cols-4">
          {shownColumns.map((column) => (
            <div key={column[0]?.label} className="min-w-0 space-y-3">
              {column.map(({ label, highlight, lead, metric, trail }) => (
                <div key={label} className="min-w-0">
                  <p className="label-micro">{label}</p>
                  <p className="mt-0.5 truncate text-caption font-bold text-ink">
                    {highlight?.lineName}
                  </p>
                  {/* Même forme que la rangée par ligne juste au-dessus : le
                      chiffre en pleine encre dans une phrase atténuée. Deux
                      façons d'écrire un chiffre dans la même section se
                      liraient comme deux natures de chiffre. */}
                  <p className="text-micro text-ink-dim">
                    {highlight !== null && (
                      <>
                        {lead}
                        <span className="font-bold text-ink tabular">{metric(highlight)}</span>
                        {trail}
                      </>
                    )}
                  </p>
                </div>
              ))}
            </div>
          ))}
          {gap !== null && (
            <div className="min-w-0">
              <p className="label-micro">Écart de fréquentation</p>
              <p className="mt-0.5 text-caption font-bold text-ink tabular">{Math.round(gap * 100)} %</p>
              <p className="text-micro text-ink-dim">Entre la ligne la plus et la moins empruntée</p>
            </div>
          )}
        </div>
      )}
    </section>
  );
}

/**
 * Un bouton de page — une cible carrée, un état grisé, et rien d'autre.
 *
 * `aria-label` et non un texte : les deux chevrons se lisent d'un coup d'œil, et
 * « Précédent » / « Suivant » écrits en clair doublaient la largeur de la barre pour
 * une information que la position du chevron donne déjà.
 */
function PageButton({
  label,
  disabled,
  onClick,
  children,
}: {
  label: string;
  disabled: boolean;
  onClick: () => void;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      aria-label={label}
      title={label}
      className="grid size-7 place-items-center rounded-input text-ink-muted transition-colors hover:enabled:bg-elevated hover:enabled:text-ink disabled:cursor-not-allowed disabled:opacity-35"
    >
      {children}
    </button>
  );
}

/**
 * Une ligne, en une seule rangée compacte : nom, solde, part, puis une barre
 * bidirectionnelle sur toute la largeur. La phrase-bilan complète
 * (`crossroadFlowSentence`) reste disponible pour les lecteurs d'écran via
 * `aria-label`, sans occuper de place à l'écran — c'est elle qui porte la
 * précision « entrer dans le carrefour, pas dans la rue ».
 */
function LineFlowRow({
  stats,
  line,
  rank,
  bordered,
}: {
  stats: AnalysisStats;
  line: CountingLine;
  /** Rang dans le tracé, 1-indexé — sert de repère quand la liste est paginée. */
  rank: number;
  bordered: boolean;
}) {
  // `lineFlows` est la seule définition du bilan d'une ligne : les comparatifs
  // ci-dessus et les cartes de la colonne de résultats lisent la même.
  const flow = lineFlows(stats, [line])[0];
  const entries = flow?.entries ?? null;
  const exits = flow?.exits ?? null;
  const forbidden = flow?.forbidden ?? null;
  const transit = flow?.transit ?? null;
  const net = entries !== null && exits !== null ? entries - exits : null;
  const share = flow?.shareOfTotal ?? null;

  return (
    <li
      aria-label={crossroadFlowSentence(line.name, entries, exits)}
      className={`p-3 ${bordered ? "border-t border-line/40" : ""}`}
    >
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        {/* Le rang, puis la pastille : le premier situe la rangée dans la liste
            paginée, la seconde la relie au trait tracé sur la vidéo. */}
        <span className="w-4 shrink-0 text-micro text-ink-dim tabular">{rank}</span>
        <span
          aria-hidden="true"
          className="size-3 shrink-0 rounded-badge"
          style={{ backgroundColor: line.color }}
        />
        <span className="min-w-0 flex-1 truncate text-caption font-semibold text-ink">{line.name}</span>

        {entries !== null && (
          <span className="text-micro text-ink-dim tabular">
            <span className="font-bold text-ink">{entries}</span> entrées
          </span>
        )}
        {exits !== null && (
          <span className="text-micro text-ink-dim tabular">
            <span className="font-bold text-ink">{exits}</span> sorties
          </span>
        )}
        {/* Le chiffre en rouge dans une phrase atténuée, exactement comme ses
            voisins : c'est la forme de toute cette section. Seule la teinte du
            nombre change, parce qu'il ne se compare pas aux entrées — il les
            contredit. */}
        {forbidden !== null && (
          <span className="text-micro text-ink-dim tabular">
            <span className="font-bold text-negative">{forbidden}</span> interdits
          </span>
        )}
        {transit !== null && (
          <span className="text-micro text-ink-dim tabular">
            <span className="font-bold text-ink">{transit}</span> passages
          </span>
        )}
        {net !== null && (
          <span className="text-micro font-bold tabular text-ink">{net > 0 ? `+${net}` : net}</span>
        )}
        {share !== null && (
          <span className="text-micro text-ink-dim tabular">{Math.round(share * 100)} % du trafic</span>
        )}
      </div>
      {entries !== null && exits !== null && (entries > 0 || exits > 0) && (
        <EntryExitBar entries={entries} exits={exits} color={line.color} />
      )}
    </li>
  );
}
