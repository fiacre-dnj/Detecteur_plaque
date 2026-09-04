/**
 * Le tableau de résultats : les chiffres du comptage, en tête de colonne.
 *
 * Un principe traverse tous ces affichages : **chaque chiffre dit d'où il vient**.
 * Le nom de la ligne plutôt qu'une flèche, l'unité dans l'aide de chaque carte.
 * Sans ces précisions, deux chiffres voisins qui ne mesurent pas la même chose se
 * confondent, et l'utilisateur tire une conclusion fausse sans jamais s'en douter.
 *
 * Deux unités cohabitent, et il ne faut jamais les diviser l'une par l'autre :
 *
 * - **véhicules** — `trackedVehicles`, `crossedUnique`, et depuis ADR 0045 le
 *   chiffre de tête. Un objet suivi, un véhicule ;
 * - **passages** — `crossings`, tous les `byLine`, toutes les cartes par ligne. Un
 *   aller-retour en vaut deux.
 *
 * C'est l'invariant 3, et il a déjà coûté un « taux de franchissement » à 200 %.
 *
 * **Trois étages, un seul chiffre de tête.**
 *
 * 1. **« Passages globaux »**, sur toute la largeur, en `size="lg"` et **collé en
 *    haut du défilement de la colonne** : c'est le chiffre auquel toutes les autres
 *    cartes se comparent, et il perdait sa fonction dès qu'il sortait de l'écran.
 *
 *    Il a compté des **passages en entrée** jusqu'à ADR 0045 — la somme des sens
 *    marqués « entrée », où un aller-retour valait deux. Il compte désormais les
 *    **véhicules distincts ayant franchi au moins une ligne**, c'est-à-dire
 *    exactement **une rangée du registre** : le même véhicule ne peut plus être
 *    compté deux fois. Le mot « Passages » couvre donc ici un compte de véhicules,
 *    ce que l'invariant 3 interdisait ; l'aide de la carte porte l'unité en toutes
 *    lettres, et les passages bruts restent lisibles sur chaque carte de ligne ;
 * 2. **la Répartition par type de véhicule**, `size="sm"`, deux par rangée. Elle
 *    n'a plus de section en bas de page pour deux raisons, aucune décorative :
 *    elle répond à la **même** question que le chiffre de tête, découpée autrement
 *    — la somme de ses cartes lui est exactement égale (`crossedByClass` compte la
 *    même population, verrouillé par un test) — et le titre « Répartition » ne
 *    disait rien de plus que « Voiture », « Bus » juste dessous. **Ses cartes
 *    suivent « Objets à compter »** : décocher « Moto » retire son KPI, parce
 *    qu'un zéro sous une classe jamais cherchée se lit comme « aucune moto n'est
 *    passée » (voir `visibleClasses`) ;
 * 3. **une carte par ligne tracée**, sur toute la largeur, avec le nom que
 *    l'utilisateur a saisi et son bilan entrées / sorties. Le détail par ligne
 *    n'existait qu'en bas de page (`LineFlowDashboard`), sous la vidéo : la
 *    question « combien sur *cette* ligne » demandait de défiler alors qu'elle se
 *    pose en même temps que le total.
 *
 * **« Objets suivis » n'est plus ici** : c'est un instantané de machine — les
 * pistes vivantes à cette image, un chiffre qui monte et descend — et il occupait
 * la moitié du meilleur emplacement de l'écran, à égalité visuelle avec le bilan
 * du comptage. Il a rejoint la cadence, la latence et le flux analysé dans la
 * barre du studio (`TechnicalMetrics`), à l'échelle qui leur revient.
 *
 * Le tableau de bord par ligne (`LineFlowDashboard`), plus détaillé et adossé aux
 * comparatifs, reste sous la vidéo — voir `StudioPage`.
 */

import { Ban } from "lucide-react";

import type { AnalysisStats, CountingLine, VehicleRecord } from "@/shared/api/contracts";
import { PERSON_CLASS, classLabel } from "@/shared/lib/classes";
import type { LineRule } from "@/shared/lib/lineRules";
import { violationCounts } from "@/shared/lib/violationTally";
import { MetricCard } from "@/shared/ui/MetricCard";
import { PanelHeading } from "@/shared/ui/PanelHeading";

import { crossedByClass } from "../model/crossedByClass";
import { crossingVehicles } from "../model/crossedVehicles";
import { crossroadFlowSentence, plural } from "../model/labels";
import { lineFlows, type LineFlow } from "../model/lineFlows";
import { visibleClasses } from "../model/visibleClasses";
import { EntryExitBar } from "./EntryExitBar";

interface ResultsDashboardProps {
  stats: AnalysisStats;
  lines: readonly CountingLine[];
  /**
   * Les véhicules du registre — **la source du chiffre de tête** depuis ADR 0045.
   *
   * L'appelant passe la même liste qu'au registre (`crossingVehicles` de l'aperçu
   * vivant ou du résultat à la tête de lecture) : c'est ce qui garantit qu'un
   * « Passages globaux » à 12 se lit sous douze rangées de tableau, et pas onze.
   * Le prédicat est réappliqué ici — `crossedVehicles.ts` reste le seul juge.
   *
   * Pas dérivable de `stats` : le serveur publie des passages par ligne et par
   * sens, pas la liste des véhicules distincts qui les ont faits. C'est
   * précisément la raison pour laquelle les deux chiffres divergeaient.
   */
  vehicles: readonly VehicleRecord[];
  /**
   * Les classes cochées dans « Objets à compter », par nom COCO (`car`,
   * `motorcycle`…), dans l'ordre du catalogue serveur.
   *
   * Calculé par l'appelant (`StudioPage`) : cette feature ne connaît ni les
   * réglages ni le catalogue de classes, seulement `AnalysisStats`/`CountingLine[]`.
   *
   * `selectedClasses` **décide des cartes affichées** : décocher « Moto » retire
   * son KPI, le recocher le rend. Une classe non cochée mais **portant des
   * entrées** dans le résultat relu garde malgré tout sa carte (voir
   * `visibleClasses` plus bas).
   */
  selectedClasses: readonly string[];
  /**
   * Les règles du tracé courant — sens interdits, voies réservées.
   *
   * Calculées par l'appelant, qui seul dispose du catalogue de classes du serveur.
   * Une `Map` vide veut dire « aucune règle », et **le KPI d'infraction n'apparaît
   * alors pas du tout** : un « 0 » sous une règle que personne n'a posée se lit
   * « aucune infraction », l'inverse de la vérité. Même honnêteté que le « — » du
   * chiffre de tête quand aucune ligne n'est tracée.
   */
  rules: ReadonlyMap<string, LineRule>;
  /**
   * L'analyse tourne-t-elle ?
   *
   * N'affecte **aucun chiffre** — seulement le repère « en direct » de l'entête,
   * le même que celui de la colonne des alertes. Sans lui, rien ne distingue à
   * l'écran des compteurs qui montent d'un résultat relu et figé : les deux
   * rendent exactement les mêmes cartes, et c'est voulu (un seul jeu de
   * composants, deux sources de même forme).
   */
  live?: boolean;
}

export function ResultsDashboard({
  stats,
  lines,
  vehicles,
  selectedClasses,
  rules,
  live = false,
}: ResultsDashboardProps) {
  // **Des véhicules distincts, et le même prédicat que le registre.** Un
  // aller-retour vaut 1 ici comme il vaut une rangée là-bas : les deux écrans se
  // vérifient l'un l'autre, ce qui était impossible tant que le chiffre de tête
  // comptait des passages.
  const crossed = crossingVehicles(vehicles);
  // Compté sur la **même liste** que le chiffre de tête, donc dans la même unité :
  // des objets distincts, jamais des passages. Le lire dans `stats.byCategory` —
  // qui compte des franchissements — mélangerait deux unités dans une seule phrase
  // (invariant 3), et un aller-retour suffirait à rendre la nuance fausse.
  const crossedPeople = crossed.filter((record) => record.label === PERSON_CLASS).length;
  const entries = crossedByClass(crossed);
  const classes = visibleClasses(selectedClasses, entries);
  const violations = violationCounts(stats, lines, rules);

  return (
    <section aria-labelledby="cards-title">
      {/* ── La tête de colonne, COLLÉE ────────────────────────────────────────
          L'entête et le chiffre de tête restent en haut quand le reste défile
          dessous. Ce n'est pas de la décoration : la colonne peut porter dix cartes
          par ligne tracée, et « Passages globaux » est le chiffre auquel toutes
          les autres se comparent — il perdait sa fonction dès qu'il sortait de
          l'écran, et il fallait remonter pour retrouver le total dont on venait de
          lire le détail.

          Trois détails qui la font tenir :

          - **`bg-base` opaque et `backdrop-blur`** : les cartes passent dessous, et
            une tête translucide sur des chiffres en mouvement est illisible ;
          - **l'entête est au **même** composant que celle des alertes**
            (`PanelHeading`) : les deux colonnes sont côte à côte à la même hauteur,
            et deux titres qui ne s'alignent pas se lisent comme deux niveaux
            d'information ;
          - **`-top-px`** et non `top-0` : un pixel de recouvrement, sinon un
            arrondi de sous-pixel laisse passer une ligne de carte au-dessus de la
            tête pendant le défilement. */}
      <div className="sticky -top-px z-10 space-y-2 bg-base/95 pb-3 pt-px backdrop-blur">
        <PanelHeading id="cards-title" title="Résultats" live={live} />

        {/* « — » et non « 0 » quand **aucune ligne n'est tracée** : sans trait, il
            n'existe aucun franchissement possible, et un zéro s'y lirait « personne
            n'est passé » alors que la vérité est « on n'a rien posé à franchir ».
            Dès qu'une ligne existe, `0` est la vérité et s'affiche.

            Le juge a changé avec l'unité : c'était `flow.declared` — « un rôle
            entrée ou sortie est-il déclaré ? » — parce que le chiffre sommait les
            sens marqués « entrée ». Il ne lit plus aucun rôle, donc une géométrie
            entièrement en « Comptage seul » rend maintenant un chiffre au lieu d'un
            tiret. */}
        <MetricCard
          size="lg"
          label="Nombre de véhicule"
          value={lines.length === 0 ? "—" : crossed.length.toString()}
          // **L'unité en toutes lettres, parce que le mot « Passages » ment ici.**
          // Le chiffre compte des véhicules : c'est la demande à laquelle ADR 0045
          // répond — plus jamais le même véhicule deux fois — et c'est une entorse
          // assumée à l'invariant 3, qui interdit de nommer des véhicules par une
          // unité de passages. L'aide est donc la seule chose qui empêche de lire
          // ce chiffre comme la somme des cartes de ligne, qui, elles, comptent
          // bien des passages.
          // **L'aide nomme les personnes dès qu'il y en a.** Le libellé dit
          // « véhicule » et le chiffre compte tout ce qui a franchi, piétons
          // compris — il le doit, puisque les cartes par type en sont la somme
          // exacte. Le tiroir promettait par ailleurs qu'elles étaient comptées
          // « à part », ce qui se lisait « pas dans ce total ». Le dire ici est ce
          // qui empêche de chercher l'écart entre le total et la somme des cartes.
          hint={
            lines.length === 0
              ? "Ajoutez une ligne dans Géométrie pour obtenir ce chiffre"
              : crossedPeople === 0
                ? "Véhicules distincts ayant franchi au moins une ligne"
                : `Objets distincts ayant franchi au moins une ligne, dont ${crossedPeople} ` +
                  `${crossedPeople > 1 ? "personnes" : "personne"}`
          }
        />
      </div>

      <div className="grid grid-cols-2 gap-2">
        {/* **L'infraction, juste sous le bilan, et seulement si une règle existe.**
            Le rouge dit ici la gravité d'un fait de la scène et non un échec de
            l'application : c'est la seule extension consentie à l'usage du jeton
            `negative`, et le mot « Franchissements interdits » porte la différence.

            Le chiffre vient de `stats` et **jamais** de la longueur du journal
            d'alertes, qui est borné : un compte plafonné affiché comme un total est
            un défaut que ce dépôt a déjà payé une fois (invariant 3). */}
        {violations.declared && (
          <div className="col-span-2">
            <div
              className={[
                "rounded-card p-4 ring-1",
                violations.total > 0
                  ? "bg-negative/10 ring-negative/40"
                  : "bg-surface shadow-card ring-transparent",
              ].join(" ")}
            >
              <div className="flex items-center gap-1.5">
                <Ban
                  aria-hidden="true"
                  className={`size-3.5 shrink-0 ${violations.total > 0 ? "text-negative" : "text-ink-dim"}`}
                />
                <span className="label-micro">Franchissements interdits</span>
              </div>
              <output
                aria-live="polite"
                className={[
                  "mt-1 block text-[1.75rem] font-bold leading-tight tabular",
                  violations.total > 0 ? "text-negative" : "text-ink",
                ].join(" ")}
              >
                {violations.total}
              </output>
              {/* Le détail des deux natures, et **seulement quand les deux
                  existent** : « 0 voie réservée » sur un tracé qui n'en déclare
                  aucune serait la même erreur de lecture, un cran plus bas. */}
              <p className="text-small text-ink-dim">
                {violationSummary(violations.forbidden, violations.reservedLane)}
              </p>
            </div>
          </div>
        )}

        {/* Le détail du chiffre de tête, dans la même grille et sous son poids :
            un type de véhicule par carte, **dans la même unité que lui** — des
            véhicules distincts, jamais des détections ni des passages, sinon la
            somme cesserait d'égaler « Passages globaux ». C'est la propriété qui
            rend ces cartes lisibles à cet endroit, et un test la verrouille. */}
        {classes.map((klass) => (
          <MetricCard
            key={klass}
            size="sm"
            label={classLabel(klass)}
            value={(entries[klass] ?? 0).toString()}
            hint="Véhicules"
          />
        ))}

        {/* Le même total, découpé par ligne cette fois — et la somme des entrées
            de ces cartes égale elle aussi le chiffre de tête. Le nom est celui
            que l'utilisateur a saisi dans le tiroir Géométrie : le renommer ou
            basculer un sens entrée ↔ sortie se voit ici **sans réanalyser**, tout
            étant dérivé de `stats.byLine` et du tracé courant. */}
        {lineFlows(stats, lines).map((line) => (
          <LineMetricCard
            key={line.lineId}
            flow={line}
            reservedLane={rules.get(line.lineId)?.allowedClasses != null}
          />
        ))}
      </div>
    </section>
  );
}

/**
 * Ce que le chiffre d'infraction recouvre, en une phrase.
 *
 * Les deux natures ne sont nommées que si les deux existent : « 0 voie réservée »
 * sur un tracé qui n'en déclare aucune se lirait comme un comptage, et c'est la
 * même erreur de lecture que le KPI lui-même existe pour éviter, un cran plus bas.
 */
function violationSummary(forbidden: number, reservedLane: number): string {
  if (forbidden > 0 && reservedLane > 0) {
    return `${forbidden} à contresens, ${reservedLane} sur voie réservée`;
  }
  if (reservedLane > 0) return "Passages sur une voie réservée à d'autres types";
  return "Passages sur un sens marqué « Interdit »";
}

/**
 * Le bilan d'une ligne : sa pastille, son nom, sa fréquentation, puis entrées,
 * sorties et solde signé.
 *
 * **Pas de flèche de sens ici.** Les trois écrans qui en portent une la pivotent
 * à l'angle réel du tracé (`directionHeadingDeg`), précisément pour qu'on relie
 * une rangée au trait qu'on voit sur la vidéo ; un pictogramme conventionnel de
 * plus contredirait cette règle. Les mots « Entrées » et « Sorties » suffisent,
 * comme dans la rangée de « Statistique ».
 *
 * Un chiffre absent (`null`) n'est **pas** affiché à zéro : aucun sens de cette
 * ligne ne porte le rôle, ce qui n'est pas la même chose que « personne n'est
 * passé ». La phrase-bilan complète part en `aria-label`, comme en bas de page —
 * c'est elle qui porte la précision « entrer dans la zone, pas dans la rue ».
 */
function LineMetricCard({
  flow,
  reservedLane,
}: {
  flow: LineFlow;
  reservedLane: boolean;
}) {
  const { entries, exits, forbidden, transit } = flow;
  const net = entries !== null && exits !== null ? entries - exits : null;

  return (
    <div
      aria-label={crossroadFlowSentence(flow.lineName, entries, exits)}
      className="col-span-2 rounded-card bg-surface p-3 shadow-card"
    >
      <div className="flex items-center gap-2">
        <span
          aria-hidden="true"
          className="size-3 shrink-0 rounded-badge"
          style={{ backgroundColor: flow.color }}
        />
        {/* `truncate` et `min-w-0` : la colonne fait 24 rem, et un nom de ligne
            long doit se couper au lieu de pousser le compteur hors de la carte. */}
        <span className="min-w-0 flex-1 truncate label-micro">{flow.lineName}</span>
        {/* La règle est annoncée sur la carte, même à zéro infraction : c'est ce qui
            distingue « rien à signaler ici » de « on ne surveille rien ici ». Le
            chiffre, lui, n'apparaît que s'il y en a un. */}
        {reservedLane && (
          <span className="shrink-0 rounded-badge bg-elevated px-1 text-micro text-ink-dim">
            voie réservée
          </span>
        )}
        <span className="shrink-0 text-micro text-ink-dim tabular">
          {plural(flow.total, "passage", "passages")}
        </span>
      </div>

      <div className="mt-2 flex flex-wrap items-baseline gap-x-4 gap-y-1">
        {entries !== null && (
          <span className="text-micro text-ink-dim">
            <span className="me-1 text-heading font-bold leading-tight text-ink tabular">
              {entries}
            </span>
            entrées
          </span>
        )}
        {exits !== null && (
          <span className="text-micro text-ink-dim">
            <span className="me-1 text-heading font-bold leading-tight text-ink tabular">
              {exits}
            </span>
            sorties
          </span>
        )}
        {/* « Interdits » prend la place de « Sorties » sur une ligne à sens unique,
            au même rang typographique : c'est le second chiffre de la ligne, celui
            qu'on lit en face du premier. En rouge parce qu'il ne se compare pas aux
            entrées — il les contredit. */}
        {forbidden !== null && (
          <span className="text-micro text-ink-dim">
            <span className="me-1 text-heading font-bold leading-tight text-negative tabular">
              {forbidden}
            </span>
            interdits
          </span>
        )}
        {transit !== null && (
          <span className="text-micro text-ink-dim">
            <span className="me-1 text-heading font-bold leading-tight text-ink tabular">
              {transit}
            </span>
            passages
          </span>
        )}
        {net !== null && (
          <span className="ms-auto text-micro font-bold tabular text-ink">
            {net > 0 ? `+${net}` : net}
          </span>
        )}
      </div>

      {entries !== null && exits !== null && (entries > 0 || exits > 0) && (
        <EntryExitBar entries={entries} exits={exits} color={flow.color} />
      )}
    </div>
  );
}
