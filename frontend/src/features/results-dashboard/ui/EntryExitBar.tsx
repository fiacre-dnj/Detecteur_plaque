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
 * `aria-hidden` : purement redondante avec les chiffres qui la précèdent.
 */

export function EntryExitBar({ entries, exits }: { entries: number; exits: number }) {
  const total = entries + exits;
  const entryShare = total === 0 ? 0 : (entries / total) * 100;
  return (
    <div
      aria-hidden="true"
      className="mt-2 flex h-1.5 overflow-hidden rounded-pill bg-elevated"
    >
      <span className="block h-full bg-ink" style={{ width: `${entryShare}%` }} />
      <span className="block h-full bg-ink-dim" style={{ width: `${100 - entryShare}%` }} />
    </div>
  );
}
