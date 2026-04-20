# Project context

This is a time-constrained AI hackathon project by a senior DevOps engineer.

Background:
- AWS, Kubernetes, Terraform, GitHub Actions, GitLab CI, Docker — strong
- Python — intermediate, functional style preferred
- Frontend/React/UX — weak, need explicit guidance

## Primary goal

Ship a working, demoable product that showcases clever use of AI.
The demo matters more than code quality — but code should be readable.

## Tech preferences

### Python projects
- Python 3.11+
- `uv` for dependency management (not pip/poetry)
- `rich` for terminal output (colored text, tables, progress bars)
- `typer` for CLI (not argparse)
- `httpx` for HTTP (not requests)
- `pydantic` for validation
- `anthropic` SDK for Claude, `openai` SDK for GPT, `google-genai` for Gemini
- Type hints on all function signatures
- Functional style over OOP unless state is genuine
- Short functions, under 30 lines when possible

### Web projects
- Next.js 15 App Router + TypeScript
- Tailwind + shadcn/ui (never roll custom UI primitives)
- Supabase for auth/DB
- Vercel for deploy
- Server components by default, client components only when interactive
- React Query for data fetching

### Avoid unless explicitly asked
- LangChain, LangGraph, CrewAI (direct API calls are simpler)
- Heavy ORMs (Prisma, SQLAlchemy) — use Supabase client or raw SQL
- Custom auth (Supabase Auth is fine)
- Microservices, k8s manifests, complex deploys (wrong scope for hackathon)
- Tests (unless requested)
- Linters/formatters/CI configs (unless requested)

## Code style

- Error handling: try/except around I/O and API calls, let logic errors bubble
- No silent failures — log visible errors
- Human-friendly error messages (for demo audience, not stack traces)
- Comments only when logic is genuinely non-obvious
- No unnecessary abstractions

## Workflow rules

### Before writing code
1. State the plan in 3-5 bullets
2. List files you will create or modify
3. Flag ambiguities, propose defaults
4. Wait for my approval

Use plan mode for tasks longer than 3 steps. For simple fixes, just do it.

### While writing code
- Use TodoWrite to track multi-step tasks
- Commit after each working unit (every 20-30 minutes)
- Conventional commit format: `feat:`, `fix:`, `chore:`, `docs:`
- Never modify files outside stated scope without asking

### After writing code
- List manual steps needed (env vars, DB migrations, API keys, OAuth apps)
- Suggest the single most valuable next step
- Do NOT suggest unrelated improvements or refactors
- If you spot issues, list them but don't fix without asking

## AI integration patterns

When I ask to "add AI" or "use an LLM":
- Default to Claude Sonnet 4: `claude-sonnet-4-20250514` via anthropic SDK
- Alternative: OpenAI gpt-4.1 or Gemini 2.5 Pro if context window matters
- System prompts: clear role + constraints + output format
- For structured output: use tool use, not prompt-based JSON extraction
- Handle API errors: rate limits, timeouts, malformed responses
- Never hardcode API keys — always environment variables
- Consider caching when responses are expensive

## Demo awareness

This code will be shown in a 2-minute demo video:
- Every user action needs visible feedback (loading state, success message, error toast)
- Empty states should be helpful, not blank
- Landing page / CLI help screen must be polished — first impression matters
- If there's a "wow moment" feature, prioritize it over secondary features

## Deployment targets

- Python CLI: runs locally, no deploy needed
- Python web/bot: Railway (simple, free tier works for demo)
- Next.js: Vercel
- Static sites: Vercel or Netlify
- Never AWS/GCP/Azure for hackathon — setup time kills you

## My knowledge profile

Strong (skip the basics):
- AWS services (EC2, S3, IAM, Lambda, VPC, EKS, ECS, RDS)
- Kubernetes (pods, services, deployments, RBAC, operators)
- Terraform (providers, modules, state management, CI/CD integration)
- Docker, docker-compose
- CI/CD pipelines
- Security scanning, secrets management
- Linux/bash proficiency

Moderate (no need for tutorials):
- Python syntax and stdlib
- SQL
- Git/GitHub workflows

Weak (explain in detail when relevant):
- React internals (hooks lifecycle, memoization)
- Advanced TypeScript (generics, conditional types)
- CSS/Tailwind mastery
- UX patterns and visual design
- Product/marketing framing

## Absolute restrictions

Never without explicit permission:
- Install new dependencies (explain why first)
- Refactor existing working code
- Add tests, linters, pre-commit hooks, CI configs
- Change project structure or move files
- Delete files
- Modify `.env` or secrets-related files
- Make breaking API changes
- Create new config files (.prettierrc, .eslintrc, etc.)

## Self-review trigger

When I ask for review of your code, answer as a senior engineer:
1. What are 3 issues you'd want fixed before deploy?
2. What edge cases are not handled?
3. What would break under realistic load/input?
4. What UX problems exist in error messages and output?

Be specific, not generic.