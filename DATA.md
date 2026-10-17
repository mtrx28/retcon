# Data

Every dataset in this repository is **either synthetic (we generated it) or public (published openly by someone
else)**. Nothing is private, login-protected, paywalled or personal. This file says which is which, where each
file came from, and how to regenerate it. (Graph Hacks rule 6.)

| What | Kind | Where in the repo | Provenance |
|---|---|---|---|
| Accounts-payable scenario: company, vendors, invoices, payments, portal pages, emails, contracts | **Synthetic** | `data/generator/`, `data/fixtures/ap_tiny.json` | Seeded generator (default seed 7) and one hand-written fixture |
| Mock bank, sandbox inbox, fake vendor portal | **Synthetic** (in-memory services) | `data/bank/`, `data/inbox/`, `data/portal/`, `data/sandbox.py` | Written by us; nothing leaves the machine |
| Science scenario: 40 retracted papers, the works that cite them, same-topic papers | **Public** | `data/fixtures/science.json` (derived), `data/science/` (the pipeline) | Retraction Watch database (via Crossref) and OpenAlex |
| Recorded Payments-agent model calls | Synthetic inputs, model outputs | `data/llm_cache/payments/` (49 files) | One Gemini run over the synthetic day, committed so it replays offline |
| Benchmark and audit results | Derived from the above | `bench/results/` | Written by `python tasks.py bench` and the audit scripts |
| Front-page pictures | **Public domain / CC0** | `ui/home/static/assets/` | Credited in `credits.json` and on the page |

## Accounts payable: synthetic, regenerable

- The company, the vendors (Coastal Produce, Harbor Dairy, Summit Packaging, Ridgeline Foods, Bluewater Seafood,
  then "Northwind Vendor 005" and so on), the people (there are none), the invoices, the amounts, the purchase
  orders, the contracts and the e-mails are all invented. Any resemblance to a real business is coincidence.
- **Bank accounts are not real.** They look like `SYN-9000-5305`, which is not an IBAN and cannot collide with
  one. E-mail addresses use the reserved `.test` domain (`ar@coastal.example.test`).
- The "compromised vendor portal" is a page our own sandbox serves. The attack text is synthetic and is aimed only
  at our own sandboxed agents. Payments go to a mock bank API, e-mails to a sandbox inbox; no real system is
  contacted.
- **Reproduce any scenario exactly:**

  ```bash
  python tasks.py gen --seed 7 --vendors 3 -o data/fixtures/ap_gen.json     # a small day
  python tasks.py gen --seed 7 --nodes 10000 -o /tmp/ap_10k.json           # the 10k-node benchmark graph
  ```

  The benchmark scenarios (`ap_1k`, `ap_10k`, `ap_prec_1k`, `ap_prec_10k`) are built in memory from seed 7 by
  `bench/harness/scenarios.py`; they are not stored. The ground truth (which memories are truly contaminated) is
  computed by an independent in-memory truth-maintenance implementation and tested to agree with the database.

## Science: public data, small derived subset

**Sources**

- **Retraction Watch database.** Crossref acquired it in September 2023 and made it publicly available
  (<https://gitlab.com/crossref/retraction-watch-data>; the dataset's own README says so). We use the retraction
  date, the publication date, the DOI and the reason field for 40 retracted papers in one subject area
  (`(BLS) Biology - Cellular`, chosen as the largest biomedical subject in the data). Reuse terms are Crossref's;
  check them before redistributing the raw CSV. **We do not redistribute the raw CSV.**
- **OpenAlex** (<https://openalex.org>), an open catalogue of scholarly works. Its data is released under CC0.
  We use titles, publication dates, DOIs, citation links, primary topics and abstracts (OpenAlex serves abstracts
  as an inverted index).

**What is committed** is `data/fixtures/science.json`: for each of 537 papers its OpenAlex id, title, DOI,
publication date and venue type; for the 40 retracted ones the retraction date and the dataset's own reason string,
**verbatim** (we describe retractions only that way and never characterise authors); and up to two short sentences
per paper taken from its abstract (1,052 in all). **No author names, institutions or countries are stored.**
The raw downloads live under `data/science/raw/`, which is git-ignored.

**A note on the sentences.** They are short quotations from abstracts, attributed to the paper by its OpenAlex id.
The abstract text remains the authors' and publishers'. If you need a fixture with no quoted text, rebuild it from
your own raw download with your own filter; nothing in the engine depends on the wording.

**Rebuild it yourself** (deterministic, no model calls, no key):

```bash
git clone --depth 1 https://gitlab.com/crossref/retraction-watch-data data/science/raw/rw
python -m pip install requests
python -I data/science/fetch_science_raw.py --subject "(BLS) Biology - Cellular" --max-retracted 40
python -I data/science/fetch_science_raw.py --add-topic-papers 8
python tasks.py science                     # writes data/fixtures/science.json
```

OpenAlex's ranking of same-topic papers drifts over time, so a rebuild can pick slightly different same-topic
papers than the committed file (the retracted and citing papers are the same). Set `OPENALEX_MAILTO` to use their
polite pool.

**How claims are chosen.** A deterministic extractor ranks abstract sentences by result cue words after dropping
what is not a claim (author lists, aims, methods, fragments). There is no language model in that step. Quality was
checked on seeded samples: `bench/results/extraction_audit.md` (sampled by seed, labelled by a **model reviewer, not
a human**; a human pass is pending) reports about one in ten sampled sentences is still not a claim. OpenAlex
occasionally returns another paper's abstract for an id; the audit flags about 1% of papers.

## The recorded model calls

`data/llm_cache/payments/` holds the 49 requests and responses of one Gemini (function calling) run over the
synthetic day, keyed by the hash of the prompt. The prompts contain only the synthetic accounts-payable data and the
agent's own tool results. Replaying them needs no key and no network. Free-tier prompts may be used by Google to
improve its products, which is acceptable for synthetic data only; do not point the live mode at real data.

## Pictures on the front page

| Picture | Credit | Licence |
|---|---|---|
| A page of the Archimedes Palimpsest | Walters Art Museum Illuminated Manuscripts, via Flickr | CC0 |
| Account Book Ledger | John Carlin, 1835 to 1856, The Metropolitan Museum of Art | CC0 |
| Chart of Factory Ledger Controlling Accounts, 1919 | Nicholson and Rohrbach, via Wikimedia Commons | Public domain |

Links are in `ui/home/static/assets/credits.json` and the front-page footer.

## What is not here

No customer data, no credentials, no scraped pages, no personal data, no paywalled content. `.env` (which can hold
a Gemini key for recording a *new* transcript) is git-ignored and excluded from the Docker image.
