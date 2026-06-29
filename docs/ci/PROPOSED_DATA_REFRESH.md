# PROPOSED — automated real-data refresh (closes the OA-11 egress gap, hands-off)

> **The problem:** the autonomous cloud loop runs in an env whose egress **blocks Polymarket**
> (403 at the proxy), so it cannot pull real resolved-market history itself — it validates on a
> committed fixture (`data/polymarket_history_sample.json`) that only grows when a human runs the
> fetcher from a network-permitted host. This stages a way to **keep that corpus fresh
> automatically** so the loop always has real out-of-sample data to validate against.
>
> The loop CANNOT do this itself (egress) and CANNOT write `.github/` headlessly — so this is
> staged for a one-time owner apply. Pick **Option A or B**.

---

## Option A (simplest — no new files): widen the env egress allowlist

If your Claude Code **environment** (FactoryDashboard, `env_01LdppMwowGrstp5M55vgJXv`) supports an
egress allowlist, add these two **public, read-only** hosts:

```
gamma-api.polymarket.com
clob.polymarket.com
```

Then the loop fetches real data itself with the code already in the repo — **zero new files, zero
secrets**. The factory routine can run `scripts/fetch_polymarket_history.py --merge` directly. This
is the cleanest fix if the allowlist is reachable in your environment settings.

---

## Option B (no egress change): a scheduled GitHub Action

GitHub-hosted runners have open internet, so they **can** reach Polymarket. This workflow refreshes
the corpus on a schedule and opens an auto-merging PR. It needs **two one-time owner steps** (a
`.github/` file + one secret), because the loop can't write `.github/` and branch protection
requires the gate to pass on any change to the default branch.

### Owner steps
1. Create a **fine-grained PAT** (scopes: this repo, `contents:write` + `pull-requests:write`) and
   add it as the repo secret **`DATA_REFRESH_PAT`**. *(A PAT — not the default `GITHUB_TOKEN` — is
   required: a PR opened by `GITHUB_TOKEN` does NOT trigger `preflight.yml`, so the required check
   would never run and the PR could never satisfy branch protection. The PAT makes the PR trigger
   the gate and auto-merge.)*
2. Add the workflow below as `.github/workflows/refresh-polymarket-data.yml`.

### Staged workflow (copy verbatim)
```yaml
name: refresh-polymarket-data
on:
  schedule:
    - cron: "17 6 * * 1"     # Mondays 06:17 UTC — weekly
  workflow_dispatch:
jobs:
  refresh:
    runs-on: ubuntu-latest    # GitHub runners CAN reach Polymarket (unlike the loop's env)
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.11" }
      - run: python -m pip install --upgrade pip && pip install requests pyyaml
      - name: Fetch + MERGE real resolved-market history (accumulate, don't overwrite)
        run: |
          python scripts/fetch_polymarket_history.py \
            --out data/polymarket_history_sample.json \
            --order volumeNum --decision-lead-days 2 --merge
      - name: Open auto-merging PR if the corpus grew
        uses: peter-evans/create-pull-request@v6
        with:
          token: ${{ secrets.DATA_REFRESH_PAT }}      # PAT so the PR triggers the required gate
          commit-message: "data: weekly Polymarket history refresh (merge)"
          branch: data/polymarket-refresh
          delete-branch: true
          title: "data: weekly Polymarket history refresh"
          body: "Automated real-data refresh (merged, dedup by market_id). Read-only public data."
      - name: Enable auto-merge on the PR
        if: steps.cpr.outputs.pull-request-number
        run: gh pr merge --squash --auto --delete-branch "${{ steps.cpr.outputs.pull-request-number }}"
        env:
          GH_TOKEN: ${{ secrets.DATA_REFRESH_PAT }}
```

Notes:
- `--merge` UNIONS new markets into the existing file by `market_id` and **never overwrites an
  earlier capture** — so the corpus accumulates across weeks (a one-shot fetch keeps returning the
  same ~current top-volume snapshot, which is why plain overwrite never grows it).
- The opened PR is **data-only**, so the `code + safety gate (blocking)` check passes and it
  auto-merges under the existing protection — no human in the loop after setup.
- No credentials are needed to *read* Polymarket (public data); the PAT is only to open the PR.

---

## After either option

The loop reads `data/polymarket_history_sample.json` from the repo it already checks out (GitHub is
reachable even though Polymarket isn't), so real OOS data flows in continuously. Tracked as
PENDING_OPS **OA-13**; supersedes the manual half of OA-11. The remaining edge work (a real model;
sampling markets earlier in their life so they're less price-pinned) stays loop-buildable
**ROADMAP track B** — not an owner action.
