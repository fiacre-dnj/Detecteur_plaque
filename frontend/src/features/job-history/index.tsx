/** Historique des analyses persistées. */

export function HistoryPage() {
  return (
    <section className="rounded-section bg-surface p-8 text-center shadow-card">
      <h2 className="text-heading font-bold text-ink">Aucune analyse pour l'instant</h2>
      <p className="mx-auto mt-2 max-w-md text-caption text-ink-muted">
        Les analyses terminées apparaîtront ici. Vous pourrez les relire sans les
        relancer, ou les rejouer avec la même configuration.
      </p>
    </section>
  );
}
