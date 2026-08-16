/**
 * Exports CSV et JSON, produits **côté client** depuis le résultat déjà chargé.
 *
 * Le serveur sait aussi exporter (`/jobs/{id}/vehicles.csv`), et c'est ce qu'il faut
 * utiliser pour un job de l'historique. Mais pendant une session de travail, le
 * résultat est déjà en mémoire : un aller-retour réseau pour reformater des données
 * qu'on possède serait du gaspillage, et il échouerait sur un job purgé alors que
 * l'utilisateur a le résultat sous les yeux.
 *
 * **Le point délicat du CSV, et il n'est pas cosmétique : le séparateur.** Excel en
 * configuration française attend le point-virgule et interprète les virgules comme
 * des décimales. Un CSV séparé par virgules s'ouvre donc **en une seule colonne**,
 * et l'utilisateur conclut que l'export est cassé. On écrit donc `sep=;` en première
 * ligne — une directive qu'Excel comprend et que les autres outils ignorent.
 */

import { directionLabel, formatSceneTime } from "@/features/results-dashboard";
import type { AnalysisResult, CountingLine, VehicleRecord } from "@/shared/api/contracts";
import { crossingDirectionName, lineName } from "@/shared/lib/directions";

/** Séparateur attendu par Excel en configuration française. */
const SEPARATOR = ";";

/**
 * Directive de séparateur, comprise par Excel et ignorée ailleurs.
 *
 * Sans elle, un CSV français s'ouvre en une colonne unique dans Excel.
 */
const SEP_DIRECTIVE = `sep=${SEPARATOR}\n`;

/**
 * BOM UTF-8.
 *
 * Sans lui, Excel lit le fichier en ANSI et affiche « VÃ©hicule » au lieu de
 * « Véhicule ». Tous les accents de l'en-tête sont concernés, donc chaque colonne.
 */
const BOM = "﻿";

/**
 * Échappe une valeur de cellule.
 *
 * Les guillemets sont doublés et la cellule entourée dès qu'elle contient un
 * séparateur, un guillemet ou un retour à la ligne — la règle du RFC 4180. Sans
 * cela, un nom de ligne contenant un point-virgule décalerait toutes les colonnes
 * suivantes.
 */
function cell(value: string | number | null): string {
  if (value === null) return "";
  const text = String(value);
  if (text.includes(SEPARATOR) || text.includes('"') || text.includes("\n")) {
    return `"${text.replace(/"/g, '""')}"`;
  }
  return text;
}

function toCsv(headers: readonly string[], rows: readonly (string | number | null)[][]): string {
  const lines = [headers.map(cell).join(SEPARATOR)];
  for (const row of rows) lines.push(row.map(cell).join(SEPARATOR));
  return BOM + SEP_DIRECTIVE + lines.join("\r\n") + "\r\n";
}

/**
 * Le registre des véhicules en CSV.
 *
 * `lines` sert à **nommer les sens** dans la colonne des franchissements : un export
 * qui dirait « l1 A→B » obligerait à rouvrir l'application pour l'interpréter, ce qui
 * annule l'intérêt d'un fichier.
 */
export function vehiclesCsv(result: AnalysisResult, lines: readonly CountingLine[]): string {
  return toCsv(
    [
      "Véhicule",
      "Type",
      "Vu de",
      "Vu à",
      "Lignes franchies",
      "Zones visitées",
      "Passages",
      "Vitesse (px/s)",
      "Vitesse (km/h)",
      // Le texte lu d'abord — c'est ce qu'on cherche —, puis les deux confiances.
      "Plaque",
      "Confiance lecture",
      "Score plaque",
    ],
    result.vehicles.map((vehicle: VehicleRecord) => [
      vehicle.globalId,
      vehicle.label,
      formatSceneTime(vehicle.firstSeenMs),
      formatSceneTime(vehicle.lastSeenMs),
      vehicle.crossedLines
        .map(
          (crossing) =>
            `${lineName(lines, crossing.lineId)} ${
              crossingDirectionName(lines, crossing.lineId, crossing.direction) ??
              directionLabel(crossing.direction)
            }`,
        )
        .join(" | "),
      vehicle.zonesVisited.join(" | "),
      vehicle.crossedLines.length,
      vehicle.avgSpeedPxS,
      vehicle.avgSpeedKmh,
      // `null` devient une case vide, **pas** « illisible » : un CSV n'est pas une vue,
      // et un mot dans cette colonne serait une valeur à nettoyer à la main avant tout
      // tri ou filtre de tableur.
      vehicle.plateText,
      vehicle.plateTextScore,
      vehicle.bestPlateScore,
    ]),
  );
}

/** Les franchissements en CSV, un par ligne. */
export function crossingsCsv(result: AnalysisResult, lines: readonly CountingLine[]): string {
  return toCsv(
    ["Ligne", "Sens", "Véhicule", "Piste", "Type", "Signe", "Horodatage", "Image", "Plaque"],
    result.crossings.map((event) => [
      lineName(lines, event.lineId),
      // Le nom du sens **et** son signe, en deux colonnes : le nom est ce qu'un
      // humain lit, le signe est ce qui reste comparable si les libellés changent.
      crossingDirectionName(lines, event.lineId, event.direction) ?? "",
      event.globalId,
      event.trackId,
      event.label,
      directionLabel(event.direction),
      formatSceneTime(event.timestampMs),
      event.frameIndex,
      // Ce que le serveur savait au moment de compter — souvent vide alors que le
      // registre porte le texte, et c'est normal (ADR 0007).
      event.plateText,
    ]),
  );
}

/**
 * Le résultat en JSON, **sans la timeline**.
 *
 * La timeline pèse l'essentiel du résultat (54 000 lignes sur une analyse de 30
 * minutes) et n'a de sens que pour rejouer la vidéo, ce qu'un fichier exporté ne
 * permet pas. L'omettre rend l'export utilisable dans un tableur ou un script ;
 * l'inclure produirait un fichier de plusieurs centaines de mégaoctets que rien
 * n'ouvrirait.
 */
export function resultJson(result: AnalysisResult): string {
  const { timeline: _timeline, ...rest } = result;
  return JSON.stringify(rest, null, 2);
}

/**
 * Déclenche le téléchargement d'un contenu texte.
 *
 * L'URL `blob:` est **révoquée** après le clic : chaque `createObjectURL` retient
 * son contenu en mémoire jusqu'à la révocation, et un utilisateur qui exporte dix
 * fois retiendrait dix copies.
 */
export function downloadText(filename: string, content: string, mime: string): void {
  const blob = new Blob([content], { type: `${mime};charset=utf-8` });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}

/**
 * Nom de fichier d'export.
 *
 * Le nom du job est repris mais **assaini** : un nom de fichier vidéo peut contenir
 * des caractères que le système de fichiers refuse, et le téléchargement échouerait
 * alors silencieusement sur certains navigateurs.
 */
export function exportFilename(jobId: string, kind: string, extension: string): string {
  const safeJob = jobId.replace(/[^a-zA-Z0-9_-]/g, "").slice(0, 16);
  return `comptage-${safeJob}-${kind}.${extension}`;
}
