/**
 * Une seule barre, deux segments côte à côte : la part d'entrées contre la part
 * de sorties d'une ligne.
 *
 * Remplaçait déjà deux barres empilées dans la rangée de « Statistique » — la
 * même comparaison en une hauteur plutôt que deux, sans rien perdre puisque les
 * chiffres sont écrits juste au-dessus. Elle a son propre fichier depuis qu'un
 * second écran la dessine : les cartes par ligne de la colonne de résultats. La
 * même comparaison doit se lire pareil aux deux endroits, et deux copies d'un
 * calcul de pourcentage finissent par diverger.
 *
 * **Elle porte la couleur de sa ligne**, celle du trait sur la vidéo et de la
 * pastille qui précède le nom. Elle était en gris d'encre : trois barres empilées
 * se ressemblaient donc toutes, et relier une rangée au trait qu'on voit à l'écran
 * demandait de relire le nom à chaque fois. La couleur encode ici une donnée — quelle
 * ligne — ce qui est le seul usage admis de la couleur dans ce projet.
 *
 * Les deux segments restent distincts **par l'opacité et non par la teinte** :
 * l'entrée est pleine, la sortie à 30 %. Une seconde teinte les distinguerait au
 * prix de la première information, qui est l'identité de la ligne.
 *
 * `aria-hidden` : purement redondante avec les chiffres qui la précèdent.
 */

export function EntryExitBar({
  entries,
  exits,
  color,
}: {
  entries: number;
  exits: number;
  /** La couleur de la ligne, telle que le canvas la trace. */
  color: string;
}) {
  const total = entries + exits;
  const entryShare = total === 0 ? 0 : (entries / total) * 100;
  return (
    <div
      aria-hidden="true"
      className="mt-2 flex h-1.5 overflow-hidden rounded-pill bg-elevated"
    >
      <span
        className="block h-full"
        style={{ width: `${entryShare}%`, backgroundColor: color }}
      />
      <span
        className="block h-full"
        style={{ width: `${100 - entryShare}%`, backgroundColor: color, opacity: 0.3 }}
      />
    </div>
  );
}
