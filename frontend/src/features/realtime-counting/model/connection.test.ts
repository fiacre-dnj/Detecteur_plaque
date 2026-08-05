import { describe, expect, test } from "bun:test";

import {
  CLOSE_INTERNAL_ERROR,
  CLOSE_POLICY_VIOLATION,
  CLOSE_TRY_AGAIN_LATER,
  REALTIME_PATH,
  closeVerdict,
  hasReason,
  realtimeUrl,
} from "./connection";

describe("realtimeUrl", () => {
  test("utilise `wss:` depuis une page `https:`", () => {
    // Obligatoire : un navigateur refuse un `ws:` non chiffré depuis une page
    // `https:` au titre du contenu mixte. Coder `ws:` en dur marcherait en
    // développement et échouerait au premier déploiement derrière TLS.
    expect(realtimeUrl({ protocol: "https:", host: "trafic.exemple.fr" })).toBe(
      `wss://trafic.exemple.fr${REALTIME_PATH}`,
    );
  });

  test("utilise `ws:` depuis une page `http:`", () => {
    expect(realtimeUrl({ protocol: "http:", host: "localhost:5173" })).toBe(
      `ws://localhost:5173${REALTIME_PATH}`,
    );
  });

  test("conserve le port — le proxy de développement en dépend", () => {
    // Le proxy de Vite écoute sur 5173 et renvoie `/api` vers 8000. Perdre le port
    // ferait viser le port 80, où rien n'écoute.
    expect(realtimeUrl({ protocol: "http:", host: "127.0.0.1:5173" })).toContain(":5173");
  });
});

describe("closeVerdict — ce que l'utilisateur peut faire", () => {
  test("1008 n'est pas réessayable : c'est la requête qui est fautive", () => {
    // Proposer « Réessayer » enverrait l'utilisateur dans une boucle d'échecs
    // identiques. Il doit corriger ses réglages.
    const verdict = closeVerdict(CLOSE_POLICY_VIOLATION, "");
    expect(verdict.retryable).toBe(false);
  });

  test("1013 est réessayable : une autre session occupe le serveur", () => {
    // C'est précisément ce qui distingue ce code du 1008, et réessayer est **la**
    // bonne action.
    expect(closeVerdict(CLOSE_TRY_AGAIN_LATER, "").retryable).toBe(true);
  });

  test("1011 est réessayable : l'erreur est côté serveur", () => {
    expect(closeVerdict(CLOSE_INTERNAL_ERROR, "").retryable).toBe(true);
  });

  test("préfère la raison du serveur, plus précise que tout texte générique", () => {
    // Elle nomme le champ fautif de l'`init` ; notre texte ne peut pas le savoir.
    const verdict = closeVerdict(CLOSE_POLICY_VIOLATION, "Init invalide : lines : au moins une ligne");
    expect(verdict.message).toBe("Init invalide : lines : au moins une ligne");
  });

  test("ne laisse jamais un message vide quand le serveur n'en donne pas", () => {
    // `event.reason` est la chaîne vide, non `undefined` : un simple test de
    // nullité passerait et l'interface afficherait un bandeau d'erreur muet.
    for (const code of [1000, 1006, 1008, 1011, 1013, 4999]) {
      expect(closeVerdict(code, "").message.length).toBeGreaterThan(10);
    }
  });

  test("1006 — la coupure réseau — reste explicable", () => {
    // Le navigateur fabrique ce code sans jamais l'accompagner d'une raison :
    // c'est le cas où le repli générique est le seul texte que l'utilisateur voit.
    const verdict = closeVerdict(1006, "");
    expect(verdict.message).toContain("connexion");
    expect(verdict.retryable).toBe(true);
  });

  test("1000 est une fin normale, pas une erreur", () => {
    expect(closeVerdict(1000, "").message).toContain("terminée");
  });

  test("ignore une raison qui n'est que des espaces", () => {
    // Sinon le bandeau afficherait un vide typographique parfaitement inutile.
    expect(closeVerdict(1013, "   ").message).toContain("déjà active");
  });
});

describe("hasReason", () => {
  test("distingue la chaîne vide de l'absence", () => {
    expect(hasReason("")).toBe(false);
    expect(hasReason("  ")).toBe(false);
    expect(hasReason(null)).toBe(false);
    expect(hasReason(undefined)).toBe(false);
    expect(hasReason("Origine refusée")).toBe(true);
  });
});
