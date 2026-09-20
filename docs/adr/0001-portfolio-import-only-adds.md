# Importing a Backup only adds, and the file has no version of its own

Importing a Backup never replaces or deletes a saved Portfolio. A Portfolio is
identified by its `id`: one with the same `id` and identical content is skipped,
and any other (a different `id`, or the same `id` with different content) is
added as a new Portfolio, taking a fresh `id` if it needed one and a `-n` suffix
on its name if that collides. Portfolios live only in the browser and deleting
one cannot be undone, so an import that overwrote could destroy work made since
the file was written, with no way back; the cost of the safe rule is a spare row
to delete by hand.

The file is a single envelope (`format`, `exportedAt`, `portfolios`) with no
version of its own. Each Portfolio inside already carries its own
`schemaVersion`, and `migratePortfolio` upgrades it on read, so a second version
number could only disagree with the first. That is the opposite of the share
link's payload, which has a `LINK_VERSION` because other people's browsers have
to read it; a Backup is read by the same app that wrote it, one Portfolio at a
time.

## Consequences

Only an exact repeat is recognised. Importing a file whose entry is an *older
version* of a portfolio since edited adds that version under a fresh id, and
importing the same file again adds it again, because the earlier copy is now a
different portfolio with a different id. Nothing is lost by it, and the extra
rows are the person's to delete. Making it idempotent would mean guessing that
a portfolio with a different id and a suffixed name is a previous import of this
one, which would also start treating a deliberate Duplicate as a repeat.

## Considered options

- **Overwrite on the same `id`** — what "restore" suggests, and the tidier
  result when undoing an edit. Rejected: it makes a stale file able to erase
  newer work silently, in the one place the app has no undo.
- **Replace the whole library on import** — rejected for the same reason, at
  the scale of every Portfolio at once.
- **Versioning the envelope** — deferred, not refused. If the envelope itself
  ever needs to change shape, the `format` marker is where a `v2` would be told
  apart from a `v1`.
