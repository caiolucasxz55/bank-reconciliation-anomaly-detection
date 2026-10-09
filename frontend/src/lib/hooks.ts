"use client";

import { useEffect, useEffectEvent, useState } from "react";

export interface Resource<T> {
  /** Latest loaded value; kept while a new key loads so the UI does not flash. */
  data: T | undefined;
  error: string | undefined;
  loading: boolean;
}

/**
 * Loads data for `key` and reloads whenever it changes. A `null` key loads nothing.
 * Loading is derived from "requested key !== loaded key" instead of being set inside
 * the effect, and stale responses are discarded through an AbortController.
 */
export function useResource<T>(
  key: string | null,
  load: (signal: AbortSignal) => Promise<T>,
): Resource<T> {
  const [state, setState] = useState<{ key: string | null; data?: T; error?: string }>({
    key: null,
  });
  const run = useEffectEvent(load);

  useEffect(() => {
    if (key === null) return;
    const controller = new AbortController();
    run(controller.signal).then(
      (data) => {
        if (!controller.signal.aborted) setState({ key, data });
      },
      (error: unknown) => {
        if (controller.signal.aborted) return;
        const message = error instanceof Error ? error.message : "Erro inesperado";
        setState((previous) => ({ key, data: previous.data, error: message }));
      },
    );
    return () => controller.abort();
  }, [key]);

  return {
    data: state.data,
    error: state.key === key ? state.error : undefined,
    loading: key !== null && state.key !== key,
  };
}

/** `value`, updated only after it stops changing for `delayMs`. */
export function useDebouncedValue<T>(value: T, delayMs: number): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delayMs);
    return () => clearTimeout(timer);
  }, [value, delayMs]);
  return debounced;
}
