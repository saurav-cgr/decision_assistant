import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";

import { createFirstPassword, getSetupStatus } from "../api/client";
import type { AuthenticatedUser, SetupStatus } from "../api/types";

type SetupContextValue = {
  status: SetupStatus | null;
  /**
   * True until the first status answer arrives. The shell must not render the sign-in form while
   * this is true: on a fresh install that form is the wrong screen, and showing it first makes the
   * operator type credentials for an account that cannot exist yet.
   */
  loading: boolean;
  /** The status request failed (or the API is unreachable) — fall back to the normal sign-in path. */
  unavailable: boolean;
  refresh: () => Promise<void>;
  createPassword: (
    password: string,
  ) => Promise<{ recoveryCode: string; user: AuthenticatedUser }>;
};

const SetupContext = createContext<SetupContextValue | null>(null);

export function SetupProvider({ children }: { children: React.ReactNode }) {
  const [status, setStatus] = useState<SetupStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [unavailable, setUnavailable] = useState(false);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      setStatus(await getSetupStatus());
      setUnavailable(false);
    } catch {
      // Deliberately swallowed into a flag rather than surfaced as an error: a failed status probe
      // must not block an install that already has a user. Falling through to the sign-in form is
      // the safe direction — the worst case is that a first-run operator sees the sign-in screen and
      // has to reload, whereas blocking the app would lock everyone out of a working install.
      setStatus(null);
      setUnavailable(true);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const value = useMemo<SetupContextValue>(
    () => ({
      status,
      loading,
      unavailable,
      refresh,
      async createPassword(password) {
        const response = await createFirstPassword(password);
        // `status.needs_password_setup` is deliberately **not** cleared here. The shell's gate reads
        // it, so clearing it unmounts the first-run screen — and with it the recovery-code step,
        // which is shown after this resolves. The code comes back from the server exactly once, so
        // unmounting here loses it for good. The screen owns the step until the operator confirms
        // they saved the code; the next mount gets a truthful status from the server.
        return { recoveryCode: response.recovery_code ?? "", user: response.user };
      },
    }),
    [status, loading, unavailable, refresh],
  );

  return <SetupContext.Provider value={value}>{children}</SetupContext.Provider>;
}

export function useSetup(): SetupContextValue {
  const value = useContext(SetupContext);
  if (!value) {
    throw new Error("useSetup must be used within SetupProvider");
  }
  return value;
}
