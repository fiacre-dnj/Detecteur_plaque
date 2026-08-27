/**
 * Les trois décisions du registre autour des captures.
 *
 * La plus importante est celle de la colonne : elle se calcule sur la liste entière
 * et jamais sur ce qui est rendu. Une colonne qui apparaîtrait au défilement d'un
 * tableau virtualisé décalerait toutes les autres sous le curseur — un défaut qui ne
 * se voit qu'en scrollant, donc jamais en relisant le code.
 */

import { describe, expect, it } from "bun:test";

import type { VehicleRecord } from "@/shared/api/contracts";

import {
  capturedVehicles,
  hasSnapshot,
  hasSnapshots,
  neighbourVehicle,
  snapshotRowHeight,
} from "./snapshots";
import { ROW_HEIGHT, SNAPSHOT_ROW_HEIGHT } from "./virtualise";

function vehicle(globalId: number, snapshotScore: number | null = null): VehicleRecord {
  return {
    globalId,
    label: "car",
    firstSeenMs: 0,
    lastSeenMs: 1_000,
    crossedLines: [],
    zonesVisited: [],
    bestPlateScore: null,
    plateText: null,
    plateTextScore: null,
    plateUnreadReason: null,
    plateBestWidthPx: null,
    plateBestGuess: null,
    plateBestGuessScore: null,
    snapshotScore,
    snapshotMs: snapshotScore === null ? null : 12_400,
  };
}

describe("hasSnapshot", () => {
  it("lit la non-nullité du score, qui est le drapeau", () => {
    expect(hasSnapshot(vehicle(1, 0.9))).toBe(true);
    expect(hasSnapshot(vehicle(1))).toBe(false);
  });

  it("traite un résultat archivé sans le champ comme sans capture", () => {
    // Un `result.json.gz` d'avant cette fonctionnalité ne porte pas la clé. Le lire
    // comme « il y a une photo » ferait afficher des images cassées sur tout le
    // registre d'une analyse ancienne.
    const legacy = { ...vehicle(1) } as Partial<VehicleRecord>;
    delete legacy.snapshotScore;
    delete legacy.snapshotMs;

    expect(hasSnapshot(legacy as VehicleRecord)).toBe(false);
  });
});

describe("hasSnapshots", () => {
  it("suffit d'une seule capture pour que la colonne existe", () => {
    expect(hasSnapshots([vehicle(1), vehicle(2, 0.8), vehicle(3)])).toBe(true);
  });

  it("est faux sur un registre sans aucune plaque lue", () => {
    expect(hasSnapshots([vehicle(1), vehicle(2)])).toBe(false);
    expect(hasSnapshots([])).toBe(false);
  });
});

describe("snapshotRowHeight", () => {
  it("ne change la densité que quand la colonne existe", () => {
    // Payer 33 % de hauteur sur toutes les analyses pour une colonne que la plupart
    // n'ont pas serait un mauvais échange.
    expect(snapshotRowHeight(false)).toBe(ROW_HEIGHT);
    expect(snapshotRowHeight(true)).toBe(SNAPSHOT_ROW_HEIGHT);
  });
});

describe("la navigation de la modale", () => {
  const shown = [vehicle(1, 0.8), vehicle(2), vehicle(3, 0.9), vehicle(4, 0.7)];

  it("ne passe que par les véhicules qui ont une photo", () => {
    // Traverser les autres afficherait une modale vide, et l'utilisateur devrait
    // deviner qu'il faut continuer à cliquer.
    expect(capturedVehicles(shown).map((entry) => entry.globalId)).toEqual([1, 3, 4]);
  });

  it("avance et recule dans l'ordre du tableau", () => {
    const list = capturedVehicles(shown);

    expect(neighbourVehicle(list, 1, 1)?.globalId).toBe(3);
    expect(neighbourVehicle(list, 3, -1)?.globalId).toBe(1);
  });

  it("ne boucle pas aux extrémités", () => {
    // Revenir au premier après le dernier fait perdre le fil sur un registre long :
    // on ne sait plus si on a tout vu.
    const list = capturedVehicles(shown);

    expect(neighbourVehicle(list, 4, 1)).toBeNull();
    expect(neighbourVehicle(list, 1, -1)).toBeNull();
  });

  it("rend `null` sur un véhicule absent de la liste", () => {
    expect(neighbourVehicle(capturedVehicles(shown), 99, 1)).toBeNull();
  });
});
