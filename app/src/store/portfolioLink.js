/**
 * portfolioLink — a portfolio, small enough to travel inside a link.
 *
 * Portfolios live in this browser's storage (portfolioStorage.js), which
 * makes one unreachable from anywhere else: no second device, and no way
 * to show somebody what you built. But a portfolio *is* only a name, an
 * amount, a rebalancing method and a handful of tickers and weights —
 * a few hundred bytes — so it can be carried by the URL itself. No
 * server-side storage, no account, and the same property the rest of the
 * app already has: the URL is the whole state.
 *
 * ## Trust
 *
 * A link is untrusted input, whoever sent it. That makes the rules here
 * the opposite of the ones in portfolioStorage: `migratePortfolio`
 * salvages what it can, because the alternative is silently losing work
 * somebody did; this module rejects the whole payload on the first thing
 * that is wrong, because the alternative is showing somebody a portfolio
 * that is not quite the one they were sent, under its author's name. A
 * half-loaded portfolio is worse than an error message.
 *
 * Nothing here writes to storage. Decoding produces a definition — no
 * id, no timestamps — and it stays a definition until the reader asks to
 * keep it, at which point it goes through `makePortfolio` like any other
 * new portfolio and becomes theirs.
 *
 * ## The encoding
 *
 * JSON with single-letter keys, UTF-8, base64url. Base64url rather than
 * `encodeURIComponent` of the JSON because percent-escaping punctuation
 * roughly doubles a payload that is mostly braces and quotes, and because
 * chat clients stop underlining a link at the first character they do not
 * consider part of one. Not compressed: a compressor is a dependency and
 * a second thing that can be wrong about a hostile input, to save a
 * couple of hundred bytes on a link nobody types by hand.
 *
 * A 20-holding portfolio comes out around 400 characters and a full
 * hundred-holding one around 1.8 kB — links that survive being pasted
 * into a chat window.
 */
import { CONTRIBUTION_FREQUENCIES, REBALANCE_FREQUENCIES } from './portfolioStorage';

/** The payload's own version, independent of the storage schema: this is
 *  a wire format that other people's browsers have to read, so it changes
 *  for its own reasons and says so in the payload.
 *
 *  Version 2 added the optional recurring contribution (#67). It had to
 *  travel: a shared portfolio that simulated without the sender's monthly
 *  payments would be a different portfolio wearing the same name, and
 *  reproducing the sender's result is the whole promise of the link. */
const LINK_VERSION = 2;

/** Payloads this build can still read. A version 1 link predates
 *  contributions and simply has none, which is a portfolio this app can
 *  represent exactly - so old links keep working rather than being
 *  refused for being old. */
const READABLE_VERSIONS = [1, 2];

/** The query parameter carrying the payload. Short because it is in
 *  every shared link. */
export const SHARE_PARAM = 'p';

/** Mirrors MAX_HOLDINGS in backend/services/portfolio.py: a link that
 *  decoded happily and then failed to simulate would be a link that is
 *  broken twice. */
export const MAX_LINK_HOLDINGS = 100;

/** Long enough for any name worth reading, short enough that the payload
 *  cannot be padded out with one. */
const MAX_NAME = 120;

/** The ceiling on the encoded payload, checked before anything is decoded
 *  — the point of a size limit is to refuse work, not to do it first. A
 *  full 100-holding portfolio encodes to roughly 1.8 kB, so this leaves
 *  room without leaving the door open. */
const MAX_PAYLOAD = 8192;

/** What a ticker can look like: the symbols yfinance and the tracked
 *  universe actually use (BRK.B, RDS-A), and nothing that could be
 *  mistaken for a path, a query or a script. */
const TICKER_PATTERN = /^[A-Z0-9][A-Z0-9.-]{0,11}$/;

/** An amount, not a number: above this it is somebody probing the parser
 *  rather than simulating a portfolio, and the chart would be unreadable
 *  either way. */
const MAX_VALUE = 1e12;

/** What every rejection ends with. The reader cannot fix a bad payload,
 *  and the sender can. */
const ASK_AGAIN = 'Ask whoever sent it for a fresh link.';

function toBase64Url(text) {
  const bytes = new TextEncoder().encode(text);
  // String.fromCharCode over the whole array blows the argument limit on
  // large inputs, and this one is bounded but not tiny.
  let binary = '';
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

function fromBase64Url(payload) {
  const base64 = payload.replace(/-/g, '+').replace(/_/g, '/');
  const binary = atob(base64 + '='.repeat((4 - (base64.length % 4)) % 4));
  const bytes = Uint8Array.from(binary, char => char.charCodeAt(0));
  // `fatal` so mangled bytes throw rather than decoding to a string full
  // of replacement characters, which would pass every check below and
  // display as somebody's portfolio with question marks in the name.
  return new TextDecoder('utf-8', { fatal: true }).decode(bytes);
}

/**
 * The payload for `portfolio`, ready to be a query parameter.
 *
 * Only the definition travels: the id, the timestamps and the `source`
 * note are facts about one library's copy, and mean nothing in another
 * browser. Weights go across as authored rather than normalised — the
 * simulation normalises them anyway, and rewriting somebody's numbers on
 * the way out would make the shared portfolio disagree with the one on
 * their screen.
 */
export function encodePortfolio(portfolio) {
  const schedule = portfolio.contribution;
  return toBase64Url(JSON.stringify({
    v: LINK_VERSION,
    n: String(portfolio.name || '').trim().slice(0, MAX_NAME),
    a: portfolio.value,
    r: portfolio.rebalance,
    h: (portfolio.holdings || []).slice(0, MAX_LINK_HOLDINGS).map(h => [h.ticker, h.weight]),
    // Omitted entirely when there is no schedule, so the common link
    // stays the length it was.
    ...(schedule ? { c: [schedule.amount, schedule.frequency] } : {}),
  }));
}

/** Rejections and successes have the same shape, so callers never have to
 *  ask which one they got. */
function bad(message) {
  return { portfolio: null, error: message };
}

/**
 * Read a payload back into a portfolio definition.
 *
 * Returns `{ portfolio, error }` with exactly one of the two set. Never
 * throws: a malformed link is an ordinary thing to receive, not an
 * exception, and it has to leave a page standing that can explain it.
 */
export function decodePortfolio(payload) {
  if (typeof payload !== 'string' || !payload) {
    return bad(`This link carries no portfolio. ${ASK_AGAIN}`);
  }
  if (payload.length > MAX_PAYLOAD) {
    return bad(`This link is too large to be a portfolio. ${ASK_AGAIN}`);
  }

  let json;
  try {
    json = fromBase64Url(payload);
  } catch {
    // Truncation is the common way to get here: chat clients and email
    // clients both cut long links, and the tail is where the holdings are.
    return bad(`This link is damaged — it may have been cut short when it was copied. ${ASK_AGAIN}`);
  }

  let raw;
  try {
    raw = JSON.parse(json);
  } catch {
    return bad(`This link is damaged and could not be read. ${ASK_AGAIN}`);
  }
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) {
    return bad(`This link does not contain a portfolio. ${ASK_AGAIN}`);
  }

  // Checked before the fields, so a payload from a future format is told
  // apart from a broken one. A newer version is the sender's app being
  // ahead of this one, which is nobody's mistake.
  if (!READABLE_VERSIONS.includes(raw.v)) {
    return bad(
      Number.isInteger(raw.v) && raw.v > LINK_VERSION
        ? 'This link was made by a newer version of this app, which this one cannot read yet.'
        : `This link is not in a format this app recognises. ${ASK_AGAIN}`
    );
  }

  const name = typeof raw.n === 'string' ? raw.n.trim() : '';
  if (!name || name.length > MAX_NAME) {
    return bad(`This link has no usable portfolio name. ${ASK_AGAIN}`);
  }

  // `typeof` first: JSON can carry a string that Number() would happily
  // turn into an amount, and "10000" is not a number somebody sent.
  if (typeof raw.a !== 'number' || !Number.isFinite(raw.a) || raw.a <= 0 || raw.a > MAX_VALUE) {
    return bad(`This link has no usable amount. ${ASK_AGAIN}`);
  }

  if (!REBALANCE_FREQUENCIES.includes(raw.r)) {
    return bad(`This link asks for a rebalancing method this app does not have. ${ASK_AGAIN}`);
  }

  if (!Array.isArray(raw.h)) {
    return bad(`This link has no holdings. ${ASK_AGAIN}`);
  }
  if (raw.h.length > MAX_LINK_HOLDINGS) {
    return bad(`This link has more than ${MAX_LINK_HOLDINGS} holdings, which is more than a portfolio here can hold.`);
  }

  const holdings = [];
  const seen = new Set();
  for (const entry of raw.h) {
    if (!Array.isArray(entry) || entry.length !== 2) {
      return bad(`This link has a holding that could not be read. ${ASK_AGAIN}`);
    }
    const [ticker, weight] = entry;
    if (typeof ticker !== 'string' || !TICKER_PATTERN.test(ticker.trim().toUpperCase())) {
      return bad(`This link contains something that is not a ticker symbol. ${ASK_AGAIN}`);
    }
    if (typeof weight !== 'number' || !Number.isFinite(weight) || weight < 0 || weight > MAX_VALUE) {
      return bad(`This link contains a weight that is not a usable number. ${ASK_AGAIN}`);
    }
    const symbol = ticker.trim().toUpperCase();
    // The same ticker twice is not a portfolio anybody built here — the
    // table is keyed by symbol — and merging the two would be a guess.
    if (seen.has(symbol)) {
      return bad(`This link holds ${symbol} twice. ${ASK_AGAIN}`);
    }
    seen.add(symbol);
    holdings.push({ ticker: symbol, weight });
  }

  // Absent on a version 1 link, and absent on a version 2 one that has no
  // schedule. Refused rather than dropped when it is present and wrong:
  // silently simulating without somebody's monthly payments would show
  // the reader a different portfolio and call it the sender's.
  let contribution;
  if (raw.c !== undefined && raw.c !== null) {
    if (!Array.isArray(raw.c) || raw.c.length !== 2) {
      return bad(`This link has a contribution that could not be read. ${ASK_AGAIN}`);
    }
    const [amount, frequency] = raw.c;
    if (typeof amount !== 'number' || !Number.isFinite(amount) || amount <= 0 || amount > MAX_VALUE) {
      return bad(`This link has a contribution that is not a usable amount. ${ASK_AGAIN}`);
    }
    if (!CONTRIBUTION_FREQUENCIES.includes(frequency)) {
      return bad(`This link contributes on a schedule this app does not have. ${ASK_AGAIN}`);
    }
    contribution = { amount, frequency };
  }

  return {
    portfolio: { name, value: raw.a, rebalance: raw.r, holdings, contribution },
    error: null,
  };
}
