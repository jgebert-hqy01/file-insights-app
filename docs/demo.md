# Demo notebook

`notebooks/demo_app.py` is a thin presentation layer over the same
registry the real app uses -- enter a filename, see which sources have it,
the summary, and one drill-down question you pick, under your own
Databricks identity. Good for showing someone what the app does before
App Service exists.

It reuses `scripts/make_smoke_bundle.py`'s zip bundle (the name predates
this notebook, but the bundle -- registry, sources, queries, masking,
validation, and the shared executor -- is exactly what both notebooks
need) and the same upload approach as the smoke test.

## Steps

### 1. Build and upload the bundle

Same as the smoke test:
```
python scripts/make_smoke_bundle.py
```
Then in the Databricks UI: **Workspace → (kebab menu) → Import**, upload
`dist/app_src.zip`. If the import doesn't preserve the folder structure,
see the "Known issue" and manual fallback in
[docs/smoke-test.md](smoke-test.md) -- it applies here too.

### 2. Upload the notebook

Import `notebooks/demo_app.py` into the **same folder** as the bundle.

### 3. Attach compute and run

Attach to serverless, or a Unity Catalog-enabled cluster on DBR 14+, then
**Run All**. The first run just creates the widgets.

### 4. Set the widgets and run again

- **filename**: a real, de-identified filename.
- **category** / **question**: cascading dropdowns built from the query
  registry. Pick a category, run the widget cell (or Run All) so the
  question dropdown narrows to that category's questions, then pick one.
- Any **filter widgets** that appear belong to *some* question in the
  registry, not necessarily your chosen one -- only the ones matching your
  current question are actually used when it runs. Leave the rest blank.

**Run All** again to see the existence check, the summary, and your chosen
question's masked result with a "produced by" footer.

### 5. Presenting it

The notebook's cell outputs are meant to be read top to bottom in a
meeting: existence check, then summary, then the chosen question. Collapse
the earlier setup cells (widgets, imports) if you want a cleaner view --
Databricks lets you collapse cells without deleting them.

## What this does and doesn't prove

Same as the smoke test (this notebook is built on the same executor):
proves the registry/queries/masking/row-cap logic against real data under
your own identity. Does **not** prove the production service principal's
auth, App Service, the Entra ID header, or the App Service-to-Databricks
network path -- see [docs/deploy.md](deploy.md). If you specifically want
the PASS/FAIL verification report rather than a presentation, run
`notebooks/smoke_test.py` instead -- see [docs/smoke-test.md](smoke-test.md).
