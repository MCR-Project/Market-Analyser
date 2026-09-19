/**
 * useMatrixOrder — the correlation matrix tab's two ordering choices
 * (issue #143), kept in the URL like every other piece of view state here
 * so a reload or a shared link opens the same matrix.
 *
 * `?matrixOrder=cluster|alpha|weight` and `?matrixWithin=weight|alpha`,
 * each its own key (the same reason `?fundMetrics=` is not just `?metrics=`),
 * written through `withParams` so nothing else in the query string is
 * dropped. A key equal to its default is omitted rather than written, so
 * the plain URL stays the default view; an unrecognised value reads as the
 * default (see `readChoice`).
 */
import { useCallback } from 'react';
import { useSearchParams } from 'react-router';
import { readChoice, withParams } from '../utils/searchParams';
import { MATRIX_ORDERS, MATRIX_WITHIN, DEFAULT_ORDER, DEFAULT_WITHIN } from '../utils/matrixOrder';

export function useMatrixOrder() {
  const [params, setParams] = useSearchParams();

  const order = readChoice(params, 'matrixOrder', MATRIX_ORDERS, DEFAULT_ORDER);
  const within = readChoice(params, 'matrixWithin', MATRIX_WITHIN, DEFAULT_WITHIN);

  const setOrder = useCallback(
    (value) => setParams(p => withParams(p, { matrixOrder: value === DEFAULT_ORDER ? null : value })),
    [setParams]
  );
  const setWithin = useCallback(
    (value) => setParams(p => withParams(p, { matrixWithin: value === DEFAULT_WITHIN ? null : value })),
    [setParams]
  );

  return { order, within, setOrder, setWithin };
}
