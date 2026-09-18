/**
 * The height range, in pixels, of the portfolio page's plot — shared by
 * PortfolioChart and ComparisonChart, which take turns in the same slot
 * of the results column, so switching to a comparison must not make the
 * chart jump to a different size (issue #139).
 *
 * The floor is the old fixed height: a chart that starts below the first
 * screenful (see useFillHeight) renders exactly as tall as it used to.
 * The ceiling keeps a tall monitor from turning the chart into a poster;
 * past it the extra height only stretches the bands.
 */
export const PLOT_MIN = 240;
export const PLOT_MAX = 600;
