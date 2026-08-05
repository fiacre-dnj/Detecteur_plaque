/** Comparaison des modèles sur cette machine. */

export function BenchmarkPage() {
  return (
    <section className="rounded-section bg-surface p-8 text-center shadow-card">
      <h2 className="text-heading font-bold text-ink">Aucune mesure enregistrée</h2>
      <p className="mx-auto mt-2 max-w-md text-caption text-ink-muted">
        Le benchmark mesure chaque modèle sur le matériel de ce serveur, sur une
        image de référence unique. Un chiffre lu hors de son contexte matériel ne
        veut rien dire : le device et la version d'Ultralytics accompagnent
        toujours le résultat.
      </p>
    </section>
  );
}
