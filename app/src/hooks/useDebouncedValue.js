import { useState, useEffect } from 'react';

/**
 * Returns a copy of `value` that only updates once `value` has stopped
 * changing for `delay` ms. Used to keep expensive downstream work (e.g. a
 * network request) from firing on every intermediate value while the user
 * is still moving — sweeping the mouse across a list, dragging a slider.
 */
export function useDebouncedValue(value, delay = 150) {
  const [debounced, setDebounced] = useState(value);

  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delay);
    return () => clearTimeout(timer);
  }, [value, delay]);

  return debounced;
}
