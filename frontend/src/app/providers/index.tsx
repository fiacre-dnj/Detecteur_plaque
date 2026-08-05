/** Composition des providers : `main.tsx` reste lisible. */

import type { ReactNode } from "react";

import { QueryProvider } from "./QueryProvider";

export function Providers({ children }: { children: ReactNode }) {
  return <QueryProvider>{children}</QueryProvider>;
}
