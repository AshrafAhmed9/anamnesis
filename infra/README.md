# Deploying Anamnesis to AWS

## Prerequisites
1. **CockroachDB Cloud cluster** (Standard, using the $400 trial credit, or Basic for free dev). Create it in the same AWS region you'll deploy Lambda to, for latency.
2. **AWS account** with Bedrock model access granted for Anthropic Claude and Amazon Titan Text Embeddings v2 (Bedrock model access is opt-in per account/region — request it in the Bedrock console first).
3. AWS SAM CLI installed (`brew install aws-sam-cli` or see AWS docs).

## Deploy

```bash
sam build --template infra/template.yaml
sam deploy --guided \
  --parameter-overrides \
    DatabaseUrl="cockroachdb+psycopg://<user>:<password>@<host>:26257/anamnesis?sslmode=verify-full" \
    BedrockRegion=us-east-1 \
    CockroachClusterId=<your-cluster-id>   # optional, enables the ccloud ops agent
```

This provisions:
- **DatabaseSecret** — an `AWS::SecretsManager::Secret` seeded from the `DatabaseUrl` parameter above. The parameter only exists to get the value into Secrets Manager at deploy time; every Lambda function receives `DATABASE_SECRET_ARN` (an ARN, not the credential) and resolves the real connection string from Secrets Manager at cold start, so it's never a plaintext Lambda environment variable.
- **ChatApiFunction** — Lambda Function URL serving the FastAPI app (`/chat`, `/memory/*`, `/metrics`, `/demo/seed`, `/health`). Set `ANAMNESIS_API_TOKEN` on the function if you want to gate the public URL behind a shared secret (give the token to judges in the Devpost testing-notes field) — `/health` always stays open.
- **ConsolidationFunction** — EventBridge-scheduled (every 30 min) Lambda that folds low-salience episodic memory into semantic beliefs and writes a JSON report to S3.
- **OpsAgentFunction** — EventBridge-scheduled (hourly) Lambda that runs the ccloud CLI ops sub-agent (see below).
- **ReportsBucket** — private S3 bucket for consolidation reports and conversation exports.

## ccloud CLI ops sub-agent — setup

The `OpsAgentFunction` shells out to the `ccloud` binary, which is not a Python package, so it must be bundled as a **Lambda layer** containing the `ccloud` binary (linux/arm64, matching this template's `Architectures: [arm64]`) or run the ops agent as a container-image Lambda instead of a zip Lambda. For the hackathon demo we run it both ways:
- **Locally / in the demo video**: run `python -m app.lambda_handlers.ops_agent` directly from a machine with `ccloud` installed and authenticated (`ccloud auth login`) — this is what the video shows.
- **In AWS**: package a container image (`Dockerfile.ops-agent`, not included by default) that installs `ccloud` in the base image, and swap `OpsAgentFunction`'s `Handler`/`ImageUri` accordingly. This is documented as a "next step" rather than shipped by default, to avoid bundling a large third-party binary in the submission repo.

### RBAC service account

Create a **least-privilege, cluster-scoped** service account for the ops
agent so it can never modify or drop the memory cluster it's monitoring.
The commands and role name below are verified against a real,
authenticated `ccloud` session and a real cluster — not guessed from the
CLI's general noun-verb pattern. (The first draft of this doc had three
commands wrong: `ccloud role-binding create` doesn't exist, `ccloud
service-account api-key create` takes the service account's *ID* plus a
key name, not just its name, and `CLUSTER_OPERATOR_VIEWER` isn't a real
role — the actual full role list, from the CLI's own validation error, is
`BILLING_COORDINATOR ORG_ADMIN ORG_MEMBER CLUSTER_ADMIN
CLUSTER_OPERATOR_WRITER CLUSTER_DEVELOPER CLUSTER_CREATOR FOLDER_ADMIN
FOLDER_MOVER`; `CLUSTER_DEVELOPER` is the closest fit for read/connect
access without operator-level write privileges on the cluster.)

```bash
# 1. Create the service account, capture its id from the output
ccloud service-account create anamnesis-ops-agent \
  --description "read-only cluster + backup introspection for Anamnesis" -o json
# -> note the "id" field, e.g. 6ab77cfc-0888-4f9b-ae80-bba2c201e2bf

# 2. Grant it CLUSTER_DEVELOPER scoped to just this cluster (not org-wide)
ccloud role add <service-account-id> CLUSTER_DEVELOPER CLUSTER <your-cluster-id>

# 3. Create an API key — the secret is shown exactly once, save it immediately
ccloud service-account api-key create <service-account-id> ops-agent-key -o json
```

Store the resulting API key in AWS Secrets Manager, never the org admin key. **Known gap**: we have not verified `ccloud`'s exact non-interactive/service-account authentication mechanism for unattended use in a Lambda container (its interactive `ccloud auth login` opens a browser, which obviously doesn't work inside Lambda) — confirm the current mechanism against the `ccloud` reference docs before wiring the container-image Lambda described below. For the hackathon demo itself, the ops agent runs from a local machine with `ccloud auth login` already completed interactively, and this exact service-account/role/API-key flow above has been run for real against the live cluster (see `docs/results/ops_agent_output.txt`).

## CockroachDB Managed MCP Server — judge's guide

Judges can inspect the live memory layer directly, read-only, without touching our code:

1. In CockroachDB Cloud Console → your cluster → **Connect** → **MCP Server**, copy the config snippet.
2. Add it to Claude Code / Cursor / VS Code's MCP config, e.g. `~/.config/claude/mcp.json`:
   ```json
   {
     "mcpServers": {
       "anamnesis-memory": {
         "url": "https://cockroachlabs.cloud/mcp",
         "headers": { "Authorization": "Bearer <read-only-token-from-console>" }
       }
     }
   }
   ```
3. Ask your AI assistant things like:
   - "Show me the currently active beliefs in semantic_memory"
   - "How many episodic memories were consolidated in the last hour?"
   - "Show the audit trail for the most recently superseded belief"

The MCP server is safe-by-default (read-only mode, full audit logging), so this is a zero-risk way to verify memory is real, transactional, structured data — not a black box.
