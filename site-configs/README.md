# Deployment Profiles

This folder contains deployment profiles consumed by `setup/setup-wizard.sh` and `scripts/build-site-stack.sh`.

Profiles can describe API stacks or nginx-only stacks. API profiles use the historical fields (`database`, `services`, `image`, `resources`, `secrets`). Nginx profiles additionally set:

- `kind: "nginx"`
- `stack.family: "nginx"`
- `stack.role`, such as `media-server`
- `services.api: false`, `services.redis: false`, and `services.database: false`
- `routing.containerPort`, usually `80` for nginx images

Nginx-only profiles must not declare API/database secrets unless the image genuinely needs them. Public static media images should keep `secrets` empty.

## Strict executable profiles

Schema `4.0` profiles may declare `renderer.type=felix-production`. For these
profiles, `environment`, `envKeys`, `secretMounts`, and enabled capability
declarations are executable inputs. The setup wizard delegates directly to the
strict Python adapter and never routes them through generic placeholder
substitution.

`site-configs/felix.json` is the first strict profile. Its companion
`felix.json.md` documents candidate/legacy isolation, digest-bound images,
local or external PostgreSQL, optional pgAdmin, Keycloak clients, and safe
capability selection. The guided wizard writes the ignored root `.env`, which
must pass validation before a stack can be rendered.
