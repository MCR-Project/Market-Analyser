# A Portfolio pays in or draws out, never both, and neither starts late

A Portfolio has at most one money-flow schedule: a Recurring Contribution or a
Recurring Withdrawal, not both. Either one begins on the first row of the first
new period after the window's start, the same rule for both, and nothing lets it
begin later. A record that somehow carries both is not simulated as either: the
library reads it as no schedule, a Backup skips that entry and says why, and a
Share Link is refused whole.

Two things make this a decision rather than a default. The money-weighted return
is defined on the property that a run's cash flows have exactly one sign change
(money in, then one closing value out, or the mirror image), which is what
guarantees one rate and lets bisection find it without a starting guess. Deposits
and withdrawals in the same run can change sign several times, and then "the rate"
may be several rates or none. And the window is view state in the URL, not a
property of the Portfolio: the same basket is looked at over a year and over a
decade. A "start withdrawing in ten years" setting would be an absolute date stored
on the Portfolio that means something different under every window.

The cost is a real use case the app cannot express: save for years, then draw
down, in one Portfolio. It can be approximated by two Portfolios over two windows.

## Consequences

The request, the stored Portfolio, the Share Link (`w`, `LINK_VERSION` 3) and the
Backup all carry the withdrawal as its own field beside `contribution` rather than
as a negative amount, so a reader that does not know about it fails visibly instead
of reading a negative `contribution.amount` as "no schedule". The editing control
is one "money flow" choice, so the invalid state cannot be reached from the UI.

Allowing both later, or a start date, is a change to what every saved
Portfolio, link and Backup means, not an added option. It would need to settle
where "when" lives first, and what the money-weighted return is when the sign
changes more than once.

## Considered options

- **Both schedules at once, independent** — the most general. Rejected: it removes
  the one-root guarantee, and a deposit and a withdrawal in the same month mostly
  cancel out.
- **A start date on the Portfolio** — the natural way to sequence saving and then
  drawing down. Rejected for now: an absolute date on the Portfolio fights the
  `?window=` view state, and a relative one ("after N years") is a second kind of
  schedule with its own rules.
- **A negative contribution amount** — no new field anywhere. Rejected: an older
  build reads an amount at or below zero as "no schedule" and would quietly show a
  withdrawal Portfolio as a lump sum, in the one place (a link somebody else opens)
  where the reader cannot ask what was meant.
