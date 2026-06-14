import { createContext, useContext, useEffect, useState, type ReactNode } from 'react';
import { authHeaders, clearToken, getToken } from '../api/auth';

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

  // On mount, if a token is stored, confirm it is still valid via /api/me.
  useEffect(() => {
    if (!getToken()) {
      setLoggedIn(false);
      return;
    }
    fetch('/api/me', { headers: authHeaders() })
      .then((r) => {
        if (r.ok) {
          setLoggedIn(true);
        } else {
          clearToken(); // stale/invalid token
          setLoggedIn(false);
        }
      })
      .catch(() => setLoggedIn(false));
  }, []);

  const logout = () => {
    clearToken();
    setLoggedIn(false);
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
