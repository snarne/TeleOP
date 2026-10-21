// Slow-changing station data: station info, org lists, settings, session.
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { live } from "../api/live";
import { api } from "../api/client";
import type { Department, Session, Settings, StationInfo, Task, User } from "../api/types";
import { useToast } from "./toasts";

interface AppData {
  station: StationInfo | null;
  departments: Department[];
  users: User[];
  tasks: Task[];
  settings: Settings | null;
  session: Session;
  loaded: boolean;
  refreshOrg: () => Promise<void>;
  setSession: (s: Partial<Session>) => Promise<void>;
  saveSettings: (s: Settings) => Promise<void>;
}

const Ctx = createContext<AppData | null>(null);

export function AppDataProvider({ children }: { children: ReactNode }) {
  const toast = useToast();
  const [station, setStation] = useState<StationInfo | null>(null);
  const [departments, setDepartments] = useState<Department[]>([]);
  const [users, setUsers] = useState<User[]>([]);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [settings, setSettings] = useState<Settings | null>(null);
  const [session, setSessionState] = useState<Session>({ operator_id: null, department_id: null, task_id: null });
  const [loaded, setLoaded] = useState(false);
  const pendingPut = useRef(0);

  // Follow session changes made elsewhere (another browser, a handle button, the CLI).
  useEffect(
    () =>
      live.onSnapshot((snap) => {
        if (pendingPut.current > 0 || !snap.session) return;
        setSessionState((cur) =>
          cur.operator_id === snap.session.operator_id && cur.department_id === snap.session.department_id && cur.task_id === snap.session.task_id ? cur : snap.session,
        );
      }),
    [],
  );

  const refreshOrg = useCallback(async () => {
    const [d, u, t] = await Promise.all([
      api.get<Department[]>("/api/departments"),
      api.get<User[]>("/api/users?include_inactive=true"),
      api.get<Task[]>("/api/tasks"),
    ]);
    setDepartments(d);
    setUsers(u);
    setTasks(t);
  }, []);

  useEffect(() => {
    let cancelled = false;
    let failures = 0;
    const load = async () => {
      try {
        const [st, se, s] = await Promise.all([
          api.get<StationInfo>("/api/station"),
          api.get<Settings>("/api/settings"),
          api.get<Session>("/api/session"),
        ]);
        if (cancelled) return;
        setStation(st);
        setSettings(se);
        setSessionState(s);
        await refreshOrg();
        setLoaded(true);
      } catch (e) {
        if (!cancelled) {
          if (failures++ === 0) toast.error(e, "Couldn't load station data");
          setTimeout(load, 3000);
        }
      }
    };
    load();
    return () => {
      cancelled = true;
    };
  }, [refreshOrg, toast]);

  const setSession = useCallback(
    async (patch: Partial<Session>) => {
      const next = { ...session, ...patch };
      setSessionState(next);
      pendingPut.current++;
      try {
        setSessionState(await api.put<Session>("/api/session", next));
      } catch (e) {
        toast.error(e, "Couldn't update the session");
      } finally {
        // let one more snapshot arrive before following the server again
        setTimeout(() => pendingPut.current--, 200);
      }
    },
    [session, toast],
  );

  const saveSettings = useCallback(
    async (s: Settings) => {
      const saved = await api.put<Settings>("/api/settings", s);
      setSettings(saved);
    },
    [],
  );

  const value = useMemo(
    () => ({ station, departments, users, tasks, settings, session, loaded, refreshOrg, setSession, saveSettings }),
    [station, departments, users, tasks, settings, session, loaded, refreshOrg, setSession, saveSettings],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAppData(): AppData {
  const c = useContext(Ctx);
  if (!c) throw new Error("useAppData outside provider");
  return c;
}
