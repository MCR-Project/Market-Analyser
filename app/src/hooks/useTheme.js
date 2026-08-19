import { useState, useCallback, useEffect } from 'react';

const STORAGE_KEY = 'theme';

// Resolution order: an explicit choice the user made on a previous visit
// (localStorage) beats the OS-level preference, which beats the hardcoded
// `initial` default — so a reload always lands back on what the user last
// saw rather than reverting to light.
function getInitialTheme(initial) {
  const stored = window.localStorage.getItem(STORAGE_KEY);
  if (stored === 'light' || stored === 'dark') return stored;
  if (window.matchMedia?.('(prefers-color-scheme: dark)').matches) return 'dark';
  return initial;
}

export function useTheme(initial = 'light') {
  const [theme, setThemeState] = useState(() => getInitialTheme(initial));

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    window.localStorage.setItem(STORAGE_KEY, theme);
  }, [theme]);

  const toggleTheme = useCallback(() => {
    setThemeState(prev => prev === 'light' ? 'dark' : 'light');
  }, []);

  return { theme, toggleTheme };
}
