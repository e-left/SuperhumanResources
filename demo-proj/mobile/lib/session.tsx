import { createContext, useContext, useEffect, useState, ReactNode } from 'react';
import { createClient } from '@supabase/supabase-js';
import * as SecureStore from 'expo-secure-store';
import { api, fixture } from './api';
import { queryClient } from './query';
const storage = { getItem: SecureStore.getItemAsync, setItem: SecureStore.setItemAsync, removeItem: SecureStore.deleteItemAsync };
export const supabase = fixture ? null : createClient(
  process.env.EXPO_PUBLIC_SUPABASE_URL ?? '', process.env.EXPO_PUBLIC_SUPABASE_PUBLISHABLE_KEY ?? '',
  { auth: { storage, persistSession: true, autoRefreshToken: true, detectSessionInUrl: false },
    global: { fetch: (input, init) => fetch(input, { ...init, signal: AbortSignal.timeout(10000) }) } },
);
type Session = { token: string | null; userId: string | null; loading: boolean;
  loginFixture: (id: string) => Promise<void>; login: (email: string, password: string) => Promise<void>; logout: () => Promise<void> };
const Context = createContext<Session | null>(null);
export function SessionProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState<string | null>(null);
  const [userId, setUserId] = useState<string | null>(null);
  const [loading, setLoading] = useState(!fixture);
  function setSession(accessToken: string | null, id: string | null) {
    queryClient.clear(); setToken(accessToken); setUserId(id);
  }
  useEffect(() => {
    if (!supabase) return;
    const { data } = supabase.auth.onAuthStateChange((_event, session) => {
      setSession(session?.access_token ?? null, session?.user.id ?? null); setLoading(false);
    });
    return () => data.subscription.unsubscribe();
  }, []);
  return <Context.Provider value={{ token, userId, loading,
    loginFixture: async id => {
      const result = await api<{ accessToken: string }>('/fixture/session', null, { userId: id });
      setSession(result.accessToken, id);
    },
    login: async (email, password) => {
      if (!supabase) throw new Error('Live authentication unavailable in fixture mode');
      const { error } = await supabase.auth.signInWithPassword({ email, password });
      if (error) throw new Error('Sign-in failed. Check credentials and Supabase connectivity.');
    },
    logout: async () => {
      if (supabase) { const { error } = await supabase.auth.signOut(); if (error) throw new Error('Sign-out failed'); }
      setSession(null, null);
    },
  }}>{children}</Context.Provider>;
}
export function useSession() { const session = useContext(Context); if (!session) throw new Error('Missing SessionProvider'); return session; }
