# Searchable Knowledge Base (Django + DRF)

Content lifecycle + permission-aware search.

```bash
pip install -r requirements.txt
python manage.py migrate
python manage.py seed_kb      # users reader/staff/editor/admin (pass1234) + sample articles, prints tokens
python manage.py runserver
python manage.py test
```

Auth: `POST /api/auth/token/` with `username` + `password`, then `Authorization: Token <key>`.

## Roles
| Role | Sees | Can do |
|---|---|---|
| anonymous / reader | public + published | read |
| staff | + internal published | read |
| editor | + drafts, archived (latest working copy) | create, edit, publish, unpublish, archive, delete |
| admin | same as editor | + restore deleted |

## Endpoints
| | |
|---|---|
| `GET /api/articles/` | filters: `category`, `status`*, `visibility`**, `ordering`; paginated |
| `GET /api/articles/search/?q=` | AND-match terms in title/body, title hits rank higher, returns `snippet` + `score` |
| `GET /api/articles/<slug>/` | 301 on renamed slug, 410 on deleted public article, else 404 |
| `GET /api/categories/` | counts reflect what *you* can see |
| `POST /api/articles/` | editor; new articles are **draft + internal** by default |
| `PATCH /api/articles/<slug>/` | title/body → new version; slug/category/visibility → metadata (slug change creates redirect) |
| `POST .../publish/` `{ "version": n }` | version optional (defaults to latest) |
| `POST .../unpublish/` `.../archive/` `.../restore/` · `DELETE ...` | soft delete |
| `GET .../versions/` | editor, full history |

\* editors only, \*\* staff+

## Design notes (the lessons from the brief)
- **Versions are immutable.** `Article.published_version` is what readers see; editing makes a new `ArticleVersion` and never touches live content until publish.
- **One visibility gate.** `selectors.visible_articles(user)` feeds list, detail, search and category counts. Search backends only ever receive that queryset (see `kb/search.py` docstring), so search can't return what detail would 404.
- **Hidden = missing.** Drafts/internal return 404 not 403; categories with nothing visible disappear; redirects only fire if the target is visible to the caller; 410 only for URLs that were once public.
- **Swapping in a search service:** implement `SearchBackend.search`, set `KB_SEARCH_BACKEND`. Let the engine return ids, then intersect with the visible queryset. Add an indexing step on publish/unpublish/delete (the `services.py` functions are the natural hook points) and index only `published_version` content for non-editor scopes.
