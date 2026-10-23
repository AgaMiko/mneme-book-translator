import { useCallback, useState } from "react";

import type { ModelCatalog, ModelStep } from "@/lib/api/client";
import { useModelCatalog } from "@/lib/api/hooks";

export interface StepModel {
  /** The model to run with: your last pick for this step, else the configured default. */
  model: string | undefined;
  setModel: (id: string) => void;
  options: ModelCatalog["options"];
  info: ModelCatalog["steps"][string] | undefined;
}

/**
 * The model picked for one pipeline step. The pick is remembered in this
 * browser for all books; a pick that is no longer offered falls back to
 * the default.
 */
export function useStepModel(step: ModelStep): StepModel {
  const catalog = useModelCatalog();
  const key = `mneme.model.${step}`;
  const [stored, setStored] = useState<string | null>(() => {
    try {
      return localStorage.getItem(key);
    } catch {
      return null;
    }
  });
  const options = catalog.data?.options ?? [];
  const info = catalog.data?.steps[step];
  const model = stored && options.some((o) => o.id === stored) ? stored : info?.default;
  const setModel = useCallback(
    (id: string) => {
      setStored(id);
      try {
        localStorage.setItem(key, id);
      } catch {
        // Private mode: the pick lasts until reload.
      }
    },
    [key],
  );
  return { model, setModel, options, info };
}
