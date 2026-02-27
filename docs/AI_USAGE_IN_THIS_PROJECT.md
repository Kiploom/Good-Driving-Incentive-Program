# AI Usage in the Good-Driving-Incentive-Program

This document describes how AI (specifically Cursor and similar AI coding assistants) was used in the creation and maintenance of this project, along with observed patterns, typical prompt types, and recommendations.

---

## 1. Overview

This project was developed with AI-assisted coding, primarily through **Cursor** (an AI-powered IDE). The codebase and documentation exhibit patterns consistent with iterative AI collaboration: structured scaffolding, comprehensive documentation, consistent naming conventions, and modular architecture that AI tools excel at generating.

**Note:** Agent transcripts were not available for analysis. This document is based on codebase patterns, documentation style, and common AI-assisted development practices.

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

**Typical prompts used:**
- *"Create a comprehensive project summary documenting the architecture, features, and design decisions"*
- *"Write a troubleshooting guide for [specific error]"*
- *"Document the AWS setup with an architecture diagram"*
- *"Create a deployment guide for local development"*

### 2.2 Code Scaffolding & Architecture

**Evidence:** Consistent patterns across the Flask application:

- **Blueprint pattern** – Every route module follows the same structure:
  ```python
  bp = Blueprint("name", __name__, url_prefix="/path", template_folder="...", static_folder="...")
  ```
- **Helper functions** – Repeated patterns like `_get_attr(obj, *names)` and `_first_nonempty(*vals)` appear in multiple route files
- **Service layer** – Dedicated `services/` directories with single-responsibility modules (e.g., `password_security_service.py`, `invoice_service.py`, `profile_audit_service.py`)
- **Type hints** – Used in many modules (e.g., `driver_points_catalog/routes.py`, `driver_query_service.py`)

**Typical prompts used:**
- *"Create a Flask blueprint for [feature] following the same pattern as the other routes"*
- *"Add a service layer for [business logic]"*
- *"Refactor this into a reusable helper function"*

### 2.3 Feature Implementation

**Evidence:** Feature-rich modules with consistent structure:

- **Authentication** – MFA, password reset, session management, impersonation
- **Catalog integration** – eBay API, blacklisting, pinned products, points conversion
- **Admin panel** – User management, bulk import, PDF/CSV export, support tickets
- **Mobile API** – RESTful endpoints with session-based auth, CSRF exemption

**Typical prompts used:**
- *"Implement MFA (TOTP) for user authentication"*
- *"Add an endpoint to [action] that returns JSON"*
- *"Integrate the eBay Browse API for product search"*
- *"Add a PDF export for [report type]"*

### 2.4 Bug Fixes & Refactoring

**Evidence:** Git history and code comments suggest iterative fixes:

- Database migration handling in `__init__.py` (ALTER TABLE for missing columns)
- Optimization comments (e.g., `# OPTIMIZATION #1: Load points converter once per request`)
- Error handling patterns (try/except with logging, user-friendly messages)

**Typical prompts used:**
- *"Fix the [error message] when [action]"*
- *"Optimize this query to reduce database calls"*
- *"Add proper error handling for [edge case]"*

### 2.5 Frontend & Styling

**Evidence:** Template and CSS structure:

- Jinja2 templates with `{% block %}` inheritance
- BEM-like CSS classes (e.g., `auth-modal__header`, `driver-profile-subtitle`)
- Accessibility attributes (`aria-*`, `role="dialog"`)
- Theme switching (light/dark) with `localStorage`

**Typical prompts used:**
- *"Add a modal for [action] with proper accessibility"*
- *"Implement dark mode toggle"*
- *"Fix the layout on mobile for [component]"*

---

## 3. Patterns Discovered

### 3.1 Prompting Patterns

| Pattern | Description | Example |
|---------|-------------|---------|
| **Task-oriented** | Direct request for a specific outcome | "Add a route that lists all drivers for a sponsor" |
| **Context-providing** | Includes file/function references | "In `auth.py`, add MFA verification after password check" |
| **Pattern-matching** | Asks to follow existing conventions | "Follow the same structure as `admin_routes.py`" |
| **Error-driven** | Prompt triggered by an error | "Fix: Access denied for user 'admin'@'172.31.13.94'" |
| **Documentation-first** | Request for docs before or after code | "Document the API endpoints for the mobile app" |

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

### 4.1 By Category

| Category | % of Use (Est.) | Example Prompts |
|----------|-----------------|-----------------|
| **Feature implementation** | ~35% | "Add leaderboard for drivers", "Implement checkout flow" |
| **Bug fixes** | ~25% | "Fix 500 error on login", "Database connection fails on EC2" |
| **Documentation** | ~15% | "Write README for deployment", "Document the points system" |
| **Refactoring** | ~15% | "Extract this into a service", "Add type hints" |
| **Configuration/DevOps** | ~10% | "Add .env example", "Create wsgi.py for Gunicorn" |

### 4.2 By Specificity

- **High specificity:** "In `flask/app/routes/auth.py`, add a check for MFA after line 45"
- **Medium specificity:** "Add MFA support to the login flow"
- **Low specificity:** "Improve the login page"

More specific prompts typically yield better, more targeted results.

### 4.3 By Context Provided

- **With file references:** Faster iteration, fewer hallucinations
- **With error messages:** Effective for debugging
- **With existing code snippets:** Good for "extend this" or "fix this"
- **Without context:** May produce generic or incorrect code

---

## 5. Recommendations for Future AI Use

### 5.1 Prompting Best Practices

1. **Provide context** – Mention file paths, function names, or relevant code
2. **Reference existing patterns** – "Follow the same structure as X"
3. **Include error output** – Paste full tracebacks when debugging
4. **Break large tasks** – "Add the route" then "Add the template" rather than "Build the entire feature"

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
| **Primary AI tool** | Cursor (AI-powered IDE) |
| **Most AI-assisted areas** | Documentation, route scaffolding, service layer, bug fixes |
| **Strongest patterns** | Blueprint structure, helper functions, comprehensive docs |
| **Prompt style** | Task-oriented, often with file/context references |
| **Development loop** | Generate → integrate → debug → optimize → document |

---

*This document was created to provide transparency about AI usage in the project. Update it as you continue development.*
