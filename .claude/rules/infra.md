---
paths:
  - "infra/**"
---
# Infrastructure rules (AWS + Terraform)

- All AWS changes through Terraform in `infra/` (`modules/`, `envs/dev`, `envs/staging`, `envs/prod`), one state per environment per stack. No click-ops; emergency changes are written back within one working day.
- Standard services: ECS Fargate, RDS PostgreSQL (Multi-AZ in prod), S3 + CloudFront, ECR, Secrets Manager, CloudWatch, WAF.
- Separate AWS account per environment (at least separate VPC, IAM roles and secrets).
- Least-privilege IAM; no wildcard actions on prod resources.
- Show `terraform plan` output to the user before any `apply`. You may apply only to dev, and only with approval. **Never plan-apply or touch `envs/prod`.**
- Before a destructive change (replace, destroy), confirm a backup or rebuild path and save previous values.
- ECS deploys use health checks and automatic rollback on failed checks or alarms. Feature flags for risky features, default off in prod.
- IaC scans (`tfsec` or `checkov`) must pass.
