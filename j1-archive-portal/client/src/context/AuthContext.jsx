import { createContext, useContext, useState } from 'react';

const AuthContext = createContext(null);

function parseToken(token) {
  try {
    const payload = JSON.parse(atob(token.split('.')[1]));
    if (payload.exp * 1000 < Date.now()) return null;
    return { token, role: payload.role, name: payload.name, sub: payload.sub };
  } catch {
    return null;
  }
}

export function AuthProvider({ children }) {
  const [auth, setAuth] = useState(() => {
    const token = localStorage.getItem('j1_token');
    return token ? parseToken(token) : null;
  });

  const login = (token, role, name) => {
    localStorage.setItem('j1_token', token);
    setAuth(parseToken(token));
  };

  const logout = () => {
    localStorage.removeItem('j1_token');
    setAuth(null);
  };

  return (
    <AuthContext.Provider value={{ auth, login, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export const useAuth = () => useContext(AuthContext);
