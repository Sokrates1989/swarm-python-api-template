# Deployment Profiles

This folder contains deployment profiles consumed by `setup/setup-wizard.sh` and `scripts/build-site-stack.sh`.

Profiles can describe API stacks or nginx-only stacks. API profiles use the historical fields (`database`, `services`, `image`, `resources`, `secrets`). Nginx profiles additionally set:

- `kind: "nginx"`
- `stack.family: "nginx"`
- `stack.role`, such as `media-server`
- `services.api: false`, `services.redis: false`, and `services.database: false`
- `routing.containerPort`, usually `80` for nginx images

Nginx-only profiles must not declare API/database secrets unless the image genuinely needs them. Public static media images should keep `secrets` empty.