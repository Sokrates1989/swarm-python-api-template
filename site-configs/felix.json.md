# Felix site profile

## Purpose and ownership

`felix.json` is a secret-free schema-5 site profile. It supplies data to the
same executable setup and deployment path available to every other app. There
is no Felix setup wizard, renderer, Keycloak adapter, secret menu, deployment
state machine, health path, log path, or rollback implementation.

Felix differs only through profile data:

- stack `felix`;
- WebApp host `felix-app.fe-wi.com`;
- API host `api.felix-app.fe-wi.com`;
- optional WebApp service enabled with image
  `sokrates1989/flutter-felix-web:1.0.8`;
- backend image `sokrates1989/python-api-felix:1.0.8` (immutable release
  default; never `latest`);
- Redis and local/external PostgreSQL;
- optional pgAdmin;
- VAPID-backed Web Push with durable scheduled dispatch;
- Keycloak realm/client defaults `felix`, `felix-frontend`, and
  `felix-backend`, with protected legacy identity, selectable realm
  settings, application roles, and temporary test identities; and
- exact Docker secret identifiers and file mounts.

Felix is enrolled in release stack `felix` with the minimum for its next
component release declared in `release.versionFloor` and component catalog
`api`, `web`, `android`, and `ios`. This deployment profile is the single
authority for that minimum; the Flutter and API repositories retain only their
own component membership. The catalog is
coordination metadata; this Swarm profile directly manages only the declared
API and WebApp services.

Felix recommends `storage.dataRoot: /swarm/prod/felix`. Pressing Enter at the
shared prompt therefore places `postgres_data`, `redis_data`, `backups`,
`logs`, and any other enabled service directory below that production clone.
Profiles with an absent or empty recommendation default to their actual
checkout instead. The common prompt also accepts another safe absolute path
when an operator intentionally wants a separate volume location.

The legacy host `felix.app.fe-wi.com` is deliberately absent from executable
routing and remains outside this stack.

## WebApp service

`services.web: true` instructs the common renderer to add the WebApp to the
same stack. The `web` object owns its image, semantic version, replicas, and
memory. `routing.web*` owns its public host, container health endpoint, and
optional direct published port. Routing also declares the default Traefik
overlay network, independent provider constraint label, certificate resolver,
and direct pgAdmin port; the shared wizard collects the actual operator
choice.

Any other app can add a WebApp in exactly the same way. Disabling
`services.web` and removing the associated WebApp fields produces an API-only
stack without modifying production code.

## Coordinated service versions

The compatibility field `release.versionFloor` stores the minimum version for
the next newly built/published Felix artifact; it does not declare that every
deployed component must already have
that version. The shared image menu queries both Docker repositories and offers
only tags that really exist. Selecting both services can advance each to its
own highest stable tag or use their highest common published tag. Exact text is
accepted only after digest and `linux/amd64` verification. After the displayed
confirmation, the shared renderer rebuilds the stack, Docker Swarm updates it,
and normal health acceptance verifies the result. No Felix-specific branch
implements this behavior.

PostgreSQL, Redis, and pgAdmin stay digest-pinned. Their adjacent track tags
(`16-alpine`, `7-alpine`, and `latest`) let the shared `a` audit report whether
the pinned digest differs from the selected registry channel without applying
an infrastructure update or inferring a database major upgrade.

## Web Push

The Felix profile enables its `webPush` capability because the shipped Flutter
PWA, Felix API, and API worker already implement the full browser subscription
and scheduled-delivery path. The shared renderer therefore mounts the matching
`FELIX_WEB_PUSH_VAPID_PUBLIC_KEY` and
`FELIX_WEB_PUSH_VAPID_PRIVATE_KEY` Docker secrets and supplies their file paths
through `WEB_PUSH_VAPID_PUBLIC_KEY_FILE` and
`WEB_PUSH_VAPID_PRIVATE_KEY_FILE`. It also enables durable dispatch with
`WEB_PUSH_DISPATCH_ENABLED=true` and uses the tracked
`mailto:operations@fe-wi.com` VAPID subject.

Run `./quick-start.sh` and select the dedicated Web Push VAPID setup action,
or open `s) Manage Docker secrets` and select the VAPID key-pair action. The
shared helper uses the host's `openssl` and `python3` to generate one P-256
pair, then creates the exact-name public and private Docker secrets without
displaying either value. Selecting either VAPID secret through the individual
secret editor redirects to the same paired workflow so mismatched keys cannot
be entered accidentally. Never write either value to `.env` or commit it.
Re-rendering the stack after the secrets exist includes the mounts
automatically. Deploying remains an explicit operator action.

Browser activation is still user-controlled. The authenticated Felix PWA asks
for notification permission, subscribes the active service worker with the
public key, stores the browser subscription through the API, and projects the
user's rolling reminder schedule. HTTPS, browser permission, an active browser
subscription, both Docker secrets, and a running dispatch worker are all
required for closed-app delivery.

## Keycloak and secrets

The running Keycloak platform remains the existing `swarm-keycloak`
deployment. The app menu uses the public Admin API of that existing server; it
never deploys another Keycloak instance and never depends on the local
development `keycloak` repository.

The shared bootstrap reads callback templates, audience-mapper policy,
application-role and temporary test-user declarations, bootstrap-reserved
usernames, protected legacy identity, backend service-account roles, the fixed
Keycloak server trust anchor, and the confidential-client Docker secret target
from this JSON. Realm/display name, all six allowlisted realm booleans, four
theme selections, localization, public SMTP sender fields, managed client IDs,
test-user lifecycle, audience, and active service roots use these profile
values as defaults but may be changed in the guided bootstrap. Valid public
selections are persisted to the ignored root `.env` and rebuild the generated
stack. The SMTP password is requested later without echo and never persists.
The administrator username/password pair is the first interactive boundary and
must also prove Admin API access before any realm question appears. Realm themes
are then selected from numbered menus populated by Keycloak's live installed
inventory. The selected login theme's server-reported locale metadata drives
the shared installer-style localization picker.

Felix's disabled-by-default sender proposal uses
`webmaster@felicitas-wisdom.com`, `smtp.strato.de:465`, implicit TLS, and the
tracked Felix display/reply-to metadata. Accepting email setup activates those
defaults; declining it keeps them available for later and leaves a live realm
sender unchanged. Email-dependent realm settings without a sender produce a
non-blocking delivery warning.
The shared flow preserves unrelated clients, social identity providers, and an
existing SMTP map when profile management remains disabled.

`secretsConfig.valueHelp` supplies the operator guidance used to generate a
temporary `secrets.env` for every manually importable exact-name Docker secret.
The shared workflow derives required/optional status from active profile
capabilities, excludes the Keycloak client credential owned by verified
bootstrap/rotation, and deletes the values file immediately after successful
creation. No Felix-specific secret template or script branch is required.
Every declared frontend callback is also admitted as a post-logout redirect,
including the native `felixkc:/callback`, while browser origins additionally
receive their Web wildcard.
The separate legacy `felixappnew` realm and declared legacy client/origin
remain protected. For Felix, the only declared backend grant is
`realm-management/manage-users`; undeclared broader grants in either the
service-account assignment or the backend client's dedicated scope, direct
realm roles other than Keycloak's generated default role, roles on undeclared
clients block automatic apply. The name `test` remains unavailable for new
automated bootstrap declarations, but an existing self-registered `test`
account is not considered tool-owned and never blocks or triggers deletion.

The profile declares the selectable production-facing role catalog `user` and
`admin`. An installer-style checkbox menu
uses Up/Down, Space, and Enter to choose the exact subset for the current run.
The bootstrap creates or updates selected roles and adds them to the restricted
frontend client's realm-role scope. These role
names are a forward-looking authorization contract; the current Felix API and
Flutter clients must still add feature-level enforcement as booking behavior
is implemented.

The initial profile default also enables two temporary identities: `user` and
`admin`. Their
role assignments and public metadata are tracked, but their passwords are not.
The dialogue asks about each identity independently, offers an exact role
multiselect from the selected catalog, asks whether its password must change at
first login, and then offers a loop for additional validated users. For a
selected missing user or password credential, the bootstrap prompts twice for
a hidden password after showing the authenticated plan and sends it only to
Keycloak. When this run actually creates an account, its username is persisted
as public cleanup-reminder state in the ignored root `.env`. The overview stays
yellow until the operator manually deletes those exact accounts and uses the
non-destructive acknowledgement action. Skipping either user or disabling this
run's user management does not
inspect, change, or auto-delete that identity and does not block unrelated
realm/client work. The tool never deletes a Keycloak user. The managed
application roles remain after manual temporary-user cleanup.

Administrator password and backend client secret are never printed, written
to `.env`, put in command arguments, or saved to a repository file. After a
new or rotated backend secret is proven and stored, the operator may opt into
a private read-only `temp_keycloak_secret.txt` editor view for recovery; the
file and its private directory are deleted immediately when the editor closes.
The bootstrap first shows a sanitized live-state plan. After apply, it reads all
owned state back and verifies themes, localization, public SMTP fields, the
public issuer, and JWKS. A new or changed authenticated SMTP configuration must
also pass Keycloak's connection-test endpoint with the runtime-only password.
Completion directs the operator to the exact Felix realm-settings Admin UI,
where themes, locales, and email settings must be reviewed, **Test connection**
must be run, and a real verification or reset email must be delivered. When
the Docker secret is missing, the real current Keycloak credential is fetched,
proven through the client-credentials token endpoint and a read-only
realm-user Admin API request. It is then streamed unchanged from memory to
`docker secret create`.

An existing Docker secret cannot be read back by Docker Swarm, so it is
reported as `present-unverified` rather than falsely described as synchronized.
Explicit rotation first regenerates and proves the Keycloak credential and
then replaces the profile-declared Docker secret while the app stack is
stopped. Because Docker secrets are immutable, replacement first creates a
temporary recovery secret containing the same proven value. It removes that
recovery object only after the fixed-name target is recreated; failures report
the recovery object name without exposing its value.

Required and optional secret names are identifiers only. Runtime values are
mounted through their declared `*_FILE` fields.

## Images, safety, and validation

API and WebApp release tags are semantic versions. Redis, PostgreSQL, and
pgAdmin images are digest pinned. Direct secret fields, mutable release aliases
such as `latest`, debug logging, wildcard origins, and unresolved placeholders
are rejected.

The profile's `imageTrackTag` fields are comparison/compatibility channels,
not runtime image references. From quick-start action `a`, the shared
infrastructure submenu reports the deployed exact digests and real compatible
registry tags. A selected same-track refresh becomes an immutable `*_IMAGE`
override in the ignored root `.env`; `felix.json` remains reusable and
unchanged. PostgreSQL requires a verified-backup checkpoint, Redis remains on
its declared major/image family, and pgAdmin's broad `latest` channel requires
an additional warning confirmation. Exact-digest reminder snoozes expire when
the registry channel changes and do not hide CVE results.

Use `./quick-start.sh`, select **Felix Backend and WebApp**, and follow the
shared setup flow. It writes root `.env` and renders one
`swarm-stack.yml`. It does not deploy until the normal deployment menu action
is selected.

Direct validation:

```bash
python3 scripts/site_profile.py --root . validate-stack --compose-check
```
