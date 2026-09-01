/**
 * Les cinq chiffres **d'instant**, posés à l'extrémité de la barre du studio.
 *
 * Pistes vivantes, cadence serveur, latence par image, écart d'affichage, durée de
 * vidéo déjà traitée : ils disent comment l'analyse se passe **en ce moment**,
 * jamais ce qu'elle a trouvé. Quatre d'entre eux occupaient quatre des six cartes
 * de tête de la colonne de résultats, au même poids visuel que le bilan du
 * comptage — donc les deux tiers de l'espace le mieux placé de l'écran pour de la
 * métrologie qu'on surveille du coin de l'œil.
 *
 * **« Écart image » est le cinquième**, et il est d'une autre nature que les
 * quatre autres : ceux-là décrivent le serveur, celui-ci décrit **l'accord entre
 * le serveur et l'écran**. Il existe parce que « on dirait que le tracker est en
 * avance » était irréfutable et invérifiable à la fois, exactement comme « cette
 * voiture est passée et elle n'est pas comptée » — et pour la même raison, il se
 * règle en donnant un chiffre plutôt qu'en discutant une impression.
 *
 * **« Objets suivis » ouvre la rangée**, et c'est le seul qui parle de
 * la scène plutôt que de la machine : c'est le nombre de pistes vivantes à *cette*
 * image, un chiffre qui monte et redescend, jamais un résultat qui s'accumule —
 * d'où sa place ici et non parmi les cartes du comptage. Sa contrepartie est
 * assumée : la `MetricCard` portait un `aria-live="polite"` sur sa valeur, cette
 * rangée non, et un compteur qui change à chaque image annoncé en continu ferait
 * d'un lecteur d'écran un métronome (la raison qui prive déjà la chronologie
 * d'`aria-live`).
 *
 * **Volontairement sobre** : une rangée de libellé-plus-chiffre, séparateurs fins,
 * aucune carte, aucune ombre. Une `MetricCard` ici les remettrait au niveau des
 * chiffres du comptage, ce qui est exactement ce qu'on vient de défaire.
 *
 * **La rangée est montée dès qu'une vidéo est chargée**, et affiche des tirets tant
 * qu'aucune analyse n'a tourné. Elle n'apparaissait auparavant qu'avec le premier
 * résultat, ce qui faisait changer la barre de forme au moment précis où l'on venait
 * de lancer — et à l'endroit où l'on regardait. Des tirets annoncent la forme de ce
 * qui vient ; c'est le même raisonnement que le squelette de la colonne de résultats.
 * Ils ne sont en revanche **pas** montés sans source : cinq tirets au-dessus d'une
 * scène vide n'annoncent rien.
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
  /**
   * Cadence de traitement du **serveur**, distincte de la lecture vidéo.
   *
   * `null` tant qu'aucune analyse n'a tourné — la rangée est montée dès l'import de la
   * vidéo et affiche alors des tirets.
   */
  processingFps: number | null;
  /**
   * Les chiffres de l'analyse, `null` avant la première.
   *
   * **Toute lecture doit être gardée.** La rangée est montée dès qu'une vidéo est
   * chargée : un `stats.activeTracks` non gardé ferait planter la barre entière, donc
   * l'écran, avant même qu'on ait lancé quoi que ce soit.
   */
  stats: AnalysisStats | null;
  /**
   * Écart entre l'image **affichée** et l'image **analysée**, en millisecondes.
   *
   * `null` quand il n'a pas été mesuré : navigateur sans `requestVideoFrameCallback`,
   * suivi désactivé, ou rien encore présenté. On affiche alors « — » plutôt qu'un
   * zéro, qui affirmerait une synchronisation qu'on n'a pas vérifiée.
   */
  displayLagMs?: number | null;
  /**
   * Comment les cinq chiffres se rangent.
   *
   * `"row"` — la rangée de la barre du studio, séparée par des filets.
   * `"grid"` — deux colonnes, quand la barre est trop étroite pour les porter et
   * qu'ils passent dans un tiroir. Les filets `border-s` d'une rangée n'y veulent
   * plus rien dire : ils séparent des voisins horizontaux.
   *
   * Une prop et non deux composants : ce sont les mêmes chiffres, avec les mêmes
   * libellés et les mêmes infobulles, et deux copies finiraient par ne plus dire la
   * même chose du même nombre.
   */
  layout?: "row" | "grid";
}

export function TechnicalMetrics({
  processingFps,
  stats,
  displayLagMs = null,
  layout = "row",
}: TechnicalMetricsProps) {
  const grid = layout === "grid";
  return (
    <dl className={grid ? "grid grid-cols-2 gap-x-5 gap-y-2.5" : "flex items-center gap-2.5"}>
      <Metric
        grid={grid}
        label="Objets suivis"
        value={stats === null ? "—" : stats.activeTracks.toString()}
        // **Un instantané, pas un total** : le nombre de pistes vivantes à cette
        // image. Il redescend quand les véhicules sortent du champ, et le lire
        // comme un cumul ferait croire à un comptage qui perd des véhicules.
        hint="Pistes vivantes à cet instant — pas un total"
      />
      <Metric
        grid={grid}
        label="Cadence serveur"
        value={processingFps !== null && processingFps > 0 ? processingFps.toFixed(1) : "—"}
        unit={processingFps !== null && processingFps > 0 ? "img/s" : undefined}
        hint="Images analysées par seconde par le serveur — pas la cadence de lecture de la vidéo"
      />
      <Metric
        grid={grid}
        label="Latence"
        value={processingFps === null ? "—" : formatFrameLatency(processingFps)}
        // Dit ce que le chiffre mesure : le traitement d'une image côté serveur,
        // et non un aller-retour réseau — en différé, il n'y en a pas par image.
        hint="Temps de traitement d'une image côté serveur"
      />
      <Metric
        grid={grid}
        label="Écart image"
        value={displayLagMs === null ? "—" : displayLagMs.toFixed(0)}
        unit={displayLagMs === null ? undefined : "ms"}
        // **Le seul chiffre qui dise si l'overlay est calé.** Les boîtes attendent
        // désormais que leur image soit affichée ; celui-ci mesure ce qu'il restait
        // d'écart au moment où elle l'a été. Il doit osciller autour de zéro. S'il
        // **dérive** avec la position dans la vidéo, la cause n'est pas le calage
        // mais la cadence déclarée du conteneur (VFR, 29,97 arrondi, rotation en
        // métadonnées) : le serveur date `index / fps`, le navigateur cherche par
        // PTS, et les deux s'éloignent. Aucun autre affichage ne sépare ces cas.
        hint="Écart entre l'image affichée et l'image analysée — proche de zéro quand l'overlay est calé"
      />
      <Metric
        grid={grid}
        label="Flux analysé"
        value={stats === null ? "—" : formatSceneTime(stats.analysedSceneMs)}
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
  grid,
}: {
  label: string;
  value: string;
  unit?: string | undefined;
  hint: string;
  grid: boolean;
}) {
  return (
    // Le filet est porté par l'élément lui-même et jamais par un `<div>` intercalé,
    // qu'un lecteur d'écran annoncerait comme un terme vide de cette `<dl>`. En
    // grille il disparaît : il sépare des voisins horizontaux, et il n'y en a plus.
    <div
      className={
        grid
          ? "flex flex-col"
          : "flex flex-col border-s border-line/60 ps-2.5 first:border-0 first:ps-0"
      }
      title={hint}
    >
      <dt className="label-micro">{label}</dt>
      {/* `text-small` (12 px) et non `text-caption` (14) : cette rangée est de la
          métrologie qu'on surveille du coin de l'œil, pas un résultat. À 14 px elle
          pesait 507 px de barre — davantage que les six pilules réunies. */}
      <dd className="text-small font-bold leading-tight text-ink tabular">
        {value}
        {unit !== undefined && (
          <span className="ms-1 text-micro font-normal text-ink-dim">{unit}</span>
        )}
      </dd>
    </div>
  );
}
