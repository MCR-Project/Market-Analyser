import { useState, useCallback, useEffect } from 'react';

export function useTheme(initial = 'light') {
  const [theme, setThemeState] = useState(initial);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
  }, [theme]);

  const toggleTheme = useCallback(() => {
    setThemeState(prev => prev === 'light' ? 'dark' : 'light');
  }, []);

  const setTheme = useCallback((t) => {
    setThemeState(t);
  }, []);

  return { theme, toggleTheme, setTheme, isLight: theme === 'light', isDark: theme === 'dark' };
}
