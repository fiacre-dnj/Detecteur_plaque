/**
 * Le Studio — l'écran unique de comptage.
 *
 * Disposition : la scène à gauche, les réglages à droite, les résultats en
 * pleine largeur dessous. C'est cette proportion qui rend l'édition de géométrie
 * confortable : le canvas a besoin de largeur, les curseurs n'en ont pas besoin.
 *
 * À ce stade, la scène et les panneaux sont des zones vides **explicites** :
 * chacune dit ce qu'il faut faire pour la remplir, comme l'exige la règle des
 * trois rendus (vide / en cours / erreur).
 */

import { Camera, FileVideo, MonitorPlay } from "lucide-react";

import { useHealth } from "@/app/layout/useHealth";
import { Button } from "@/shared/ui/Button";
import { MetricCard } from "@/shared/ui/MetricCard";

const SOURCES = [
  { icon: FileVideo, label: "Fichier vidéo", hint: "Glissez un clip ou parcourez" },
  { icon: MonitorPlay, label: "Vidéo de démonstration", hint: "Un clip fourni pour essayer" },
  { icon: Camera, label: "Caméra", hint: "Comptage en direct sur la webcam" },
] as const;

export function StudioPage() {
  const { data: health } = useHealth();
  const serverReady = health != null;

  return (
    <div className="space-y-6">
      <section aria-labelledby="source-title">
        <h2 id="source-title" className="label-micro mb-3">
          Source à analyser
        </h2>
        <div className="grid gap-3 sm:grid-cols-3">
          {SOURCES.map(({ icon: Icon, label, hint }) => (
            <button
              key={label}
              type="button"
              disabled
              className="rounded-card bg-surface p-4 text-start transition-colors hover:bg-elevated disabled:cursor-not-allowed disabled:opacity-60"
            >
              <Icon aria-hidden="true" className="size-5 text-ink-dim" />
              <p className="mt-3 text-caption font-bold text-ink">{label}</p>
              <p className="mt-0.5 text-small text-ink-dim">{hint}</p>
            </button>
          ))}
        </div>
        <p className="mt-3 text-small text-ink-dim">
          Les images sont envoyées au serveur, qui réalise l'analyse.
        </p>
      </section>

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_20rem]">
        <section
          aria-label="Scène"
          className="flex aspect-video items-center justify-center rounded-section bg-surface shadow-card"
        >
          <p className="max-w-xs text-center text-caption text-ink-dim">
            Choisissez une source pour afficher la scène et tracer vos lignes de
            comptage.
          </p>
        </section>

        <aside aria-label="Réglages" className="space-y-4">
          <div className="rounded-section bg-surface p-4 shadow-card">
            <h3 className="label-micro">Détection</h3>
            <p className="mt-3 text-small text-ink-dim">
              {serverReady
                ? `Modèle par défaut : ${health.defaultModelId} · ${health.device === "cpu" ? "CPU" : "CUDA"}`
                : "Le serveur est injoignable : le sélecteur de modèle sera disponible à sa reconnexion."}
            </p>
          </div>

          <Button
            variant="primary"
            className="w-full"
            disabled
            title={
              serverReady
                ? "Ajoutez d'abord une ligne de comptage"
                : "Le serveur est injoignable"
            }
          >
            Lancer l'analyse serveur
          </Button>
        </aside>
      </div>

      <section aria-labelledby="results-title">
        <h2 id="results-title" className="label-micro mb-3">
          Résultats
        </h2>
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <MetricCard label="Véhicules uniques" value="—" hint="Tous types confondus" />
          <MetricCard label="Franchissements" value="—" hint="Somme des deux sens" />
          <MetricCard label="Ré-identifications" value="—" hint="Retours après occlusion" />
          <MetricCard
            label="Débit estimé"
            value="—"
            hint="Disponible après 3 s de flux analysé"
          />
        </div>
      </section>
    </div>
  );
}
