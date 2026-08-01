Figures live in `<year>.journal`, plain-text [hledger](https://hledger.org) accounting: one
file per year, appended to, never edited by hand for a past entry. This is the only source of
amounts anywhere in the vault; [[02 Clients/README|02 Clients]] holds terms and context, never a
number. Ask your agent for a total and it runs `hledger` against this file and reads you the
real result, not a cached one.
