import { createContext, useContext, useEffect, useState, type ReactNode } from 'react';
import { logout as apiLogout } from '../api/auth';

interface AuthContextValue {
  loggedIn: boolean;
  setLoggedIn: (v: boolean) => void;
  logout: () => void;
}

const AuthContext = createContext<AuthContextValue>({
  loggedIn: false,
  setLoggedIn: () => {},
  logout: () => {},
});

export function AuthProvider({ children }: { children: ReactNode }) {
  const [loggedIn, setLoggedIn] = useState(false);

  // On mount, confirm the session via /api/me. This also plants the CSRF
  // cookie the SPA needs for subsequent unsafe requests.
  useEffect(() => {
    fetch('/api/me', { credentials: 'include' })
      .then((r) => setLoggedIn(r.ok))
      .catch(() => setLoggedIn(false));
  }, []);

  const logout = () => {
    apiLogout().finally(() => setLoggedIn(false));
  };

  return (
    <AuthContext.Provider value={{ loggedIn, setLoggedIn, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  return useContext(AuthContext);
}
