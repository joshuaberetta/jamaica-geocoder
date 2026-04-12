import { createContext, useContext, useEffect, useState, type ReactNode } from 'react';

interface AuthContextValue {
  loggedIn: boolean;
  setLoggedIn: (v: boolean) => void;
}

const AuthContext = createContext<AuthContextValue>({ loggedIn: false, setLoggedIn: () => {} });

export function AuthProvider({ children }: { children: ReactNode }) {
  const [loggedIn, setLoggedIn] = useState(false);

  useEffect(() => {
    fetch('/api/auth')
      .then((r) => r.json())
      .then((data: { logged_in: boolean }) => setLoggedIn(data.logged_in))
      .catch(() => setLoggedIn(false));
  }, []);

  return (
    <AuthContext.Provider value={{ loggedIn, setLoggedIn }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  return useContext(AuthContext);
}
