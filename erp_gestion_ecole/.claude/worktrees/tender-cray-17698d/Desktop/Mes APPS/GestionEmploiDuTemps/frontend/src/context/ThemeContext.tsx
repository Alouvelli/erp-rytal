import { createContext, useContext, useState, useEffect, ReactNode } from 'react';

interface ThemeContextType { dark: boolean; toggle: () => void; }
const ThemeContext = createContext<ThemeContextType>(null!);

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [dark, setDark] = useState(() => localStorage.getItem('theme') === 'dark');

  useEffect(() => {
    document.documentElement.classList.toggle('dark', dark);
    localStorage.setItem('theme', dark ? 'dark' : 'light');
  }, [dark]);

  return <ThemeContext.Provider value={{ dark, toggle: () => setDark(!dark) }}>{children}</ThemeContext.Provider>;
}

export const useTheme = () => useContext(ThemeContext);
