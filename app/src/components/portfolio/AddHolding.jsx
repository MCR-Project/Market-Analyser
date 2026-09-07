/**
 * AddHolding — putting a ticker into a portfolio.
 *
 * The picking and the checking belong to TickerSearchField, shared with
 * the benchmark bar: choosing a symbol and confirming it can be priced is
 * the same question wherever it is asked, and #58 built two endpoints for
 * exactly it.
 *
 * What is left here is what happens to a holding once it is in — the note
 * saying it lists partway through the window, so nobody has to wonder
 * later why their backtest starts flat.
 */
import { useState } from 'react';
import { TickerSearchField } from './TickerSearchField';

export function AddHolding({ existing, windowStart, onAdd }) {
  const [note, setNote] = useState(null);

  const add = (resolved) => {
    onAdd(resolved.symbol);
    setNote(
      windowStart && resolved.firstDate && resolved.firstDate > windowStart
        ? `${resolved.symbol} has prices from ${resolved.firstDate}. Until then its share of the portfolio waits in cash.`
        : null
    );
  };

  return (
    <div className="mb-3">
      <TickerSearchField
        placeholder="Add a holding — ticker or name"
        ariaLabel="Add a holding"
        exclude={existing.map(holding => holding.ticker)}
        onResolved={add}
      />
      {note && (
        <p role="status" className="text-[12.5px] text-[var(--fg-2)] leading-relaxed m-0 mt-2">
          {note}
        </p>
      )}
    </div>
  );
}
