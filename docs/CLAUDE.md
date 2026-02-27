# CLAUDE.md (Short Version)

## AI-Assisted Development Workflow — Grant Benson

---

## 1. How I Build Projects From Scratch Using AI

My workflow for creating new full-stack applications is based on using AI as a co-architect and pair programmer:

**Define the feature and constraints myself first**

- I write a small spec describing roles, data flow, and user interactions.
- This spec becomes the "North Star" for the AI.

**Use ChatGPT to refine the architecture**

- schema design
- route definitions
- service boundaries
- AWS infrastructure
- mobile/React structure
- file trees

This ensures the AI isn't guessing — it's following a plan.

**Generate the project foundation through Cursor's Composer**

- Composer builds the initial file tree, boilerplate, and folder structure.
- I then iteratively expand features with small scoped prompts.

This process was heavily used in the Good Driving Incentive Program, where I designed the backend, mobile API, points system, and admin tools using this iterative AI-first approach ([AI_USAGE_IN_THIS_PROJECT](AI_USAGE_IN_THIS_PROJECT.md)).

---

## 2. How I Prepare Prompts

I use structured, reusable prompt templates. A typical one looks like:

```
You are my senior engineer.
Goal: [feature]
Tech stack: [Flask, RDS, Kotlin, Next.js]
Constraints: [security, multi-tenant logic, API shape]
Context: [paste relevant files or models]
Output: full file, no placeholders.
```

I always provide:

- context files
- relevant functions
- existing patterns
- expected output format

The more context I give the agent, the better the entire project stays consistent.

For big features, I use ChatGPT to create prompts for Cursor, so that Cursor receives clean, scoped instructions optimized for its file-editing capabilities.

---

## 3. How I Debug Using AI

I separate "explanation" from "execution":

**ChatGPT = diagnostics**

- Explain errors
- Identify root cause
- Suggest minimal, safe fixes
- Provide commands for testing
- Offer multiple hypotheses
- Map AWS networking issues (SGs, subnets, ports)

**Cursor = implementation**

- Once ChatGPT finds the actual bug, I highlight code blocks in Cursor and say:
  - *Apply the fix ChatGPT suggested, but preserve surrounding logic.*
  - *Explain what changes you made.*

This workflow drastically reduces hallucinated fixes.

---

## 4. How I Verify AI's Results

I use a trust-but-verify approach:

**Programmatic checks**

- Run tests or sample requests
- Check API responses
- Validate JWTs or session flows
- Confirm SQL queries manually
- Use Postman to simulate edge cases

**Architectural checks**

- Ensure code matches my spec
- Ensure file naming matches project conventions
- Confirm that security logic (auth, roles, points checking) is correct
- Validate data flows (especially in multi-tenant systems)

**Manual review**

- I read all AI-written code line-by-line before committing.
- If something "looks too generic," I rewrite it myself.

---

## 5. Feeding AI Context (The Most Important Skill)

I feed context strategically, not blindly.

**Cursor**

- Paste relevant file(s) directly
- Select multiple files for the agent to read before generating a new one
- Highlight small blocks for scoped diffs
- Use "Composer" for multi-file initialization
- Use "Auto" to let the agent modify several files only when I supervise changes

**ChatGPT**

- I paste batches of files only when I need architectural review
- I give summaries of the codebase rather than raw dumps
- I feed error logs, stack traces, and AWS settings during debugging

**Cross-AI workflow**

- ChatGPT sometimes acts as the planner, and Cursor acts as the executor:
  - ChatGPT writes ideal prompts
  - Cursor uses those prompts to apply code changes
  - I review the diffs

---

## 6. How I Use Composer + Auto in Cursor

**Composer**

I use Composer to:

- bootstrap new features
- generate entire modules (e.g., a new points converter, admin routes, or a new catalog screen)
- create consistent file trees
- build component scaffolding in Next.js and Kotlin

**Auto**

Used sparingly, usually for:

- updating related files
- propagating type changes
- modifying service layers when models update

Auto is powerful, but I always review the diff before accepting changes.

---

## 7. How I Learn from AI to Become a Better Developer

Working with AI has taught me:

1. **How to think in clean abstractions** — AI works best when the architecture is clean. That forced me to design clean.
2. **How to write clearer specifications** — If AI misunderstands, it means my spec wasn't good enough.
3. **How to identify root causes faster** — AI explanations often reveal mental models I can compare with my own.
4. **How to maintain consistency** — AI demands consistent patterns across codebases — a good habit to adopt.
5. **How to read more code than I write** — AI writing code means I spend more time reviewing, analyzing, and refactoring — which made me a stronger engineer.

---

## 8. How I Used AI Specifically on the Good Driver Incentive Program

Using the provided file's analysis, here's the distilled version of how AI drove that project:

- AI helped generate full Flask blueprints, service layers, admin tools, and multi-tenant sponsor logic
- AI generated documentation: project summaries, deployment guides, AWS diagrams, troubleshooting docs, etc. ([AI_USAGE_IN_THIS_PROJECT](docs/AI_USAGE_IN_THIS_PROJECT.md))
- AI scaffolded the entire mobile API and admin panel
- AI wrote consistent HTML/Jinja templates with accessible modals and responsive layouts
- AI assisted in complex multi-file refactors (e.g., catalog logic, points system)
- AI helped debug EC2, RDS, and Nginx issues that otherwise would've taken days
- AI generated migration scripts and SQL patterns matching the rest of the codebase

This project shows my ability to:

- control large AI-assisted codebases
- build advanced features
- debug production-level issues
- maintain architectural coherence
