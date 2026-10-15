import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api";

export function useLoad<T = any>(path: string, interval = 0) {
  const [state, setState] = useState<{
    path: string;
    data: T | null;
    error: string;
  }>({ path, data: null, error: "" });
  const requestId = useRef(0);
  const controller = useRef<AbortController>();
  const reload = useCallback(async () => {
    const id = ++requestId.current;
    controller.current?.abort();
    const request = new AbortController();
    controller.current = request;
    try {
      const data = await api<T>(path, { signal: request.signal });
      if (id === requestId.current) setState({ path, data, error: "" });
    } catch (e) {
      if (id === requestId.current && !request.signal.aborted)
        setState((previous) => ({
          path,
          data: previous.path === path ? previous.data : null,
          error: (e as Error).message,
        }));
    }
  }, [path]);
  useEffect(() => {
    let disposed = false;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      await reload();
      if (!disposed && interval) timer = setTimeout(poll, interval);
    };
    void poll();
    return () => {
      disposed = true;
      ++requestId.current;
      controller.current?.abort();
      clearTimeout(timer);
    };
  }, [reload, interval]);
  return {
    data: state.path === path ? state.data : null,
    error: state.path === path ? state.error : "",
    reload,
  };
}
