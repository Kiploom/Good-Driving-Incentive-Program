# AI Usage in the Good-Driving-Incentive-Program

This document describes how AI (specifically Cursor and similar AI coding assistants) was used in the creation and maintenance of this project, along with observed patterns, typical prompt types, and recommendations.

---

## 1. Overview

This project was developed with AI-assisted coding, primarily through **Cursor** (Composer, Auto) and **ChatGPT**, following the workflow described in [claude.md](claude.md). Prompts were structured with *Goal*, *Tech stack*, *Constraints*, *Context*, and *Output* to ensure consistent, scoped results. The codebase exhibits patterns from this iterative approach: structured scaffolding, comprehensive documentation, consistent naming conventions, and modular architecture.

**Note:** Agent transcripts were not available for analysis. This document is based on codebase patterns, documentation style, and the prompt structure defined in claude.md.

---

## 2. How AI Was Used

### 2.1 Documentation Generation

**Evidence:** The `docs/` folder contains highly structured, comprehensive documentation:

| Document | AI-Assisted Characteristics |
|----------|-----------------------------|
| `PROJECT_SUMMARY.md` | ~600+ lines, hierarchical structure, tables for tech stack and features, consistent formatting |
| `ASSETS_NEEDED.md` | Checklist format, file/folder structure, template update instructions |
| `LOCAL_DEPLOYMENT.md` | Step-by-step setup, environment variable tables, multi-platform commands |
| `TROUBLESHOOTING_DB.md` | Error-focused structure, numbered steps, code blocks for diagnostics |
| `AWS_OVERVIEW.md` | ASCII architecture diagram, component tables, SSH/CLI examples |

**Typical prompts used** (structured per [claude.md](claude.md)):

```
You are my senior engineer.
Goal: Create a comprehensive project summary documenting architecture, features, and design decisions.
Tech stack: Flask, MySQL, Kotlin (Android), Jinja2.
Constraints: Must cover all three roles (driver, sponsor, admin), security measures, and deployment.
Context: [paste app/__init__.py, models.py, key route files]
Output: Full markdown file, no placeholders.
```

```
Goal: Write a troubleshooting guide for RDS connection errors.
Context: [paste error log, .env structure, TROUBLESHOOTING_DB.md if exists]
Output: Numbered steps, code blocks for diagnostics, security group checklist.
```

### 2.2 Code Scaffolding & Architecture

**Evidence:** Consistent patterns across the Flask application:

- **Blueprint pattern** – Every route module follows the same structure:
  ```python
  bp = Blueprint("name", __name__, url_prefix="/path", template_folder="...", static_folder="...")
  ```
- **Helper functions** – Repeated patterns like `_get_attr(obj, *names)` and `_first_nonempty(*vals)` appear in multiple route files
- **Service layer** – Dedicated `services/` directories with single-responsibility modules (e.g., `password_security_service.py`, `invoice_service.py`, `profile_audit_service.py`)
- **Type hints** – Used in many modules (e.g., `driver_points_catalog/routes.py`, `driver_query_service.py`)

**Typical prompts used** (structured per [claude.md](claude.md)):

```
You are my senior engineer.
Goal: Create a Flask blueprint for [feature] (e.g., support tickets, leaderboard).
Tech stack: Flask, SQLAlchemy, Blueprints.
Constraints: Follow same pattern as admin_routes.py and driver_routes.py; use @login_required; include template_folder/static_folder.
Context: [paste admin_routes.py, driver_routes.py structure]
Output: Full file, no placeholders.
```

```
Goal: Add a service layer for [business logic].
Constraints: Single responsibility; no DB access in routes for complex logic; match existing services (e.g., password_security_service.py).
Context: [paste relevant route file, model]
Output: New service file + minimal route changes.
```

### 2.3 Feature Implementation

**Evidence:** Feature-rich modules with consistent structure:

- **Authentication** – MFA, password reset, session management, impersonation
- **Catalog integration** – eBay API, blacklisting, pinned products, points conversion
- **Admin panel** – User management, bulk import, PDF/CSV export, support tickets
- **Mobile API** – RESTful endpoints with session-based auth, CSRF exemption

**Typical prompts used** (structured per [claude.md](claude.md)):

```
You are my senior engineer.
Goal: Implement MFA (TOTP) for user authentication.
Tech stack: Flask, Flask-Login, pyotp.
Constraints: Must work with existing auth flow; store secret encrypted (Fernet); support recovery codes; require MFA for sensitive actions.
Context: [paste auth.py, models.py Account/MFA fields]
Output: Full implementation, no placeholders.
```

```
Goal: Integrate eBay Browse API for product search.
Tech stack: Flask, requests, eBay Browse API v1.
Constraints: Respect rate limits; handle auth (OAuth); return JSON for mobile API; support category filtering.
Context: [paste config, existing catalog structure]
Output: Provider class + route integration.
```

### 2.4 Bug Fixes & Refactoring

**Evidence:** Git history and code comments suggest iterative fixes:

- Database migration handling in `__init__.py` (ALTER TABLE for missing columns)
- Optimization comments (e.g., `# OPTIMIZATION #1: Load points converter once per request`)
- Error handling patterns (try/except with logging, user-friendly messages)

**Typical prompts used** (structured per [claude.md](claude.md)):

```
Goal: Fix [error message] when [action].
Context: [paste full stack trace, relevant code block]
Constraints: Minimal change; preserve surrounding logic; add logging if appropriate.
Output: Apply the fix; explain what changed.
```

```
Goal: Optimize this query to reduce database calls.
Context: [paste route/function with N+1 or repeated queries]
Constraints: Use batch loading, caching, or single query; match existing patterns (e.g., get_points_converter).
Output: Refactored code with comment explaining optimization.
```

### 2.5 Frontend & Styling

**Evidence:** Template and CSS structure:

- Jinja2 templates with `{% block %}` inheritance
- BEM-like CSS classes (e.g., `auth-modal__header`, `driver-profile-subtitle`)
- Accessibility attributes (`aria-*`, `role="dialog"`)
- Theme switching (light/dark) with `localStorage`

**Typical prompts used** (structured per [claude.md](claude.md)):

```
Goal: Add a modal for [action] (e.g., change email, MFA setup) with proper accessibility.
Tech stack: Jinja2, Bootstrap 5, vanilla JS.
Constraints: Use aria-* attributes, role="dialog", focus trap, BEM-like classes (auth-modal__header).
Context: [paste base.html, existing modal if any]
Output: Full modal markup + JS; no placeholders.
```

```
Goal: Implement dark mode toggle.
Constraints: Use localStorage; respect prefers-color-scheme; apply to existing theme.css; no flash on load.
Context: [paste base.html, theme.css]
Output: Inline script + CSS updates.
```

---

## 3. Patterns Discovered

### 3.1 Prompting Patterns

Prompts followed the structured template from [claude.md](claude.md): *Goal*, *Tech stack*, *Constraints*, *Context*, *Output*.

| Pattern | Description | Structured Example |
|---------|-------------|-------------------|
| **Task-oriented** | Direct request for a specific outcome | `Goal: Add a route that lists all drivers for a sponsor. Context: [sponsor_routes.py]` |
| **Context-providing** | Includes file/function references | `Goal: Add MFA verification after password check. Context: [auth.py lines 40–60]` |
| **Pattern-matching** | Asks to follow existing conventions | `Constraints: Follow same structure as admin_routes.py. Context: [admin_routes.py]` |
| **Error-driven** | Prompt triggered by an error | `Goal: Fix Access denied for user 'admin'@'172.31.13.94'. Context: [stack trace, .env]` |
| **Documentation-first** | Request for docs before or after code | `Goal: Document the mobile API endpoints. Output: Markdown with tables, code blocks.` |

### 3.2 Code Patterns (AI-Generated or AI-Assisted)

| Pattern | Location | Description |
|---------|----------|-------------|
| **Private helpers** | Routes, services | `_get_attr`, `_parse_num`, `_require_driver_and_sponsor` – underscore prefix for module-private |
| **Decorator chains** | Route handlers | `@bp.route(...)` + `@login_required` + custom decorators |
| **Service injection** | `__init__.py`, routes | Services imported and used; no direct DB in routes for complex logic |
| **Consistent error responses** | API routes | `jsonify({"error": "...", "message": "..."})` with appropriate status codes |
| **Docstrings** | Functions, modules | Triple-quoted, first-line summary, sometimes with `"""` only |

### 3.3 Documentation Patterns

| Pattern | Example |
|---------|---------|
| **Tables for structured data** | Tech stack, env vars, file lists |
| **Code blocks with language tags** | ` ```bash `, ` ```python ` |
| **Numbered steps** | "Step 1: Clone...", "Step 2: Create venv..." |
| **Horizontal rules** | `---` between major sections |
| **Checklists** | `- [ ]` or bullet lists for tasks |

### 3.4 Iterative Development Pattern

The codebase suggests a **generate → review → refine** loop:

1. **Initial generation** – AI produces scaffolding or feature code
2. **Integration** – Developer wires it into the app, runs it
3. **Debugging** – Error occurs; developer prompts AI with error context
4. **Optimization** – Comments like `# OPTIMIZATION #1` indicate later refinement passes
5. **Documentation** – Docs added or updated to reflect changes

---

## 4. Types of Prompts Used (Inferred)

Prompts were structured using the [claude.md](claude.md) template to ensure consistent, scoped output.

### 4.1 By Category

| Category | % of Use (Est.) | Structured Example |
|----------|-----------------|---------------------|
| **Feature implementation** | ~35% | `Goal: Add leaderboard for drivers. Tech stack: Flask, SQLAlchemy. Constraints: Sponsor-scoped, points-based. Context: [leaderboard.py, PointChange model]` |
| **Bug fixes** | ~25% | `Goal: Fix 500 error on login. Context: [stack trace, auth.py]. Constraints: Minimal change, preserve logic.` |
| **Documentation** | ~15% | `Goal: Document deployment. Output: Step-by-step, env var table, multi-platform commands.` |
| **Refactoring** | ~15% | `Goal: Extract [logic] into a service. Constraints: Match password_security_service pattern. Context: [route file]` |
| **Configuration/DevOps** | ~10% | `Goal: Create wsgi.py for Gunicorn. Tech stack: Flask. Constraints: Production-ready, no dev server.` |

### 4.2 By Specificity

- **High specificity:** `Goal: Add MFA check after password verification. Context: auth.py lines 45–55. Output: Insert block, explain changes.`
- **Medium specificity:** `Goal: Add MFA support to login flow. Tech stack: Flask, pyotp. Context: [auth.py]`
- **Low specificity:** `Goal: Improve the login page.` (Avoided when possible; structured prompts yield better results.)

### 4.3 By Context Provided

Per [claude.md](claude.md), context was fed strategically:

- **With file references:** Paste relevant files; select multiple for Composer
- **With error messages:** Full stack trace + relevant code for debugging
- **With existing code snippets:** "Extend this" or "Apply fix to this block"
- **Cross-AI workflow:** ChatGPT drafted prompts; Cursor executed with full context

---

## 5. Recommendations for Future AI Use

### 5.1 Prompting Best Practices

Follow the structured template from [claude.md](claude.md):

1. **Use Goal + Tech stack + Constraints + Context + Output** – Ensures scoped, consistent results
2. **Provide context** – Paste relevant files, function names, or code blocks
3. **Reference existing patterns** – Include "Constraints: Follow same structure as X"
4. **Include error output** – Paste full tracebacks when debugging
5. **Break large tasks** – Separate "Add the route" from "Add the template" rather than "Build the entire feature"

### 5.2 Code Review Checklist

When using AI-generated code:

- [ ] Verify security (no hardcoded secrets, proper input validation)
- [ ] Check database queries (SQL injection, N+1 issues)
- [ ] Test edge cases (empty inputs, null values)
- [ ] Ensure consistency with project conventions
- [ ] Update documentation if behavior changes

### 5.3 Documentation Maintenance

- Keep `PROJECT_SUMMARY.md` updated when adding major features
- Add troubleshooting entries when resolving recurring issues
- Document AI-generated sections with a note if needed for academic integrity

### 5.4 Academic Integrity (CPSC 4910)

If this project is submitted for grading:

- Disclose AI usage per course policy
- Be prepared to explain and modify any AI-generated code
- Use AI as a tool, not a substitute for understanding

---

## 6. Summary

| Aspect | Finding |
|--------|---------|
| **Primary AI tool** | Cursor (Composer, Auto), ChatGPT (architecture, debugging) |
| **Prompt style** | Structured per [claude.md](claude.md): Goal, Tech stack, Constraints, Context, Output |
| **Most AI-assisted areas** | Documentation, route scaffolding, service layer, bug fixes |
| **Strongest patterns** | Blueprint structure, helper functions, comprehensive docs |
| **Development loop** | Generate → integrate → debug → optimize → document |

---

*This document was created to provide transparency about AI usage in the project. Update it as you continue development.*
