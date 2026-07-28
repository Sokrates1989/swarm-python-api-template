# Proxy Configuration Guide

Proxy configuration is collected by the same site-config-driven setup dialogue
used for every deployment profile. A public profile can allow Traefik,
directly published ports, or both. Internal-only profiles skip this section.

## Configure through quick-start

On the Linux Swarm host:

```bash
./quick-start.sh
```

Choose **Run setup wizard**, select the deployment profile, and use the
numbered **Proxy and TLS** section. Press Enter to accept each displayed
profile or existing-`.env` default.

The active production workflow is Bash. There is no maintained
`quick-start.ps1` or `setup-wizard.ps1`; use WSL only when the Bash flow needs
to be inspected from Windows.

Do not copy old environment or stack templates manually. The wizard writes
root `.env` and renders `swarm-stack.yml` from the selected profile and
operator answers.

## Traefik

Choose Traefik when an existing Swarm Traefik service owns domain routing.

The wizard then collects:

1. TLS ownership;
2. the existing Traefik public overlay network; and
3. the Traefik provider constraint label; and
4. the certificate resolver when Traefik owns certificates.

The network picker enumerates real overlay networks and highlights a declared
or commonly named Traefik network. Select the network to which the existing
Traefik service is attached. Do not select an app-specific backend network and
do not create a new overlay unless Traefik will also be reconfigured to use it.
The provider constraint label is independent: it must match the label value
configured on the Traefik Swarm provider, even when the selected overlay has a
different name.

The resulting public values are stored in `.env`:

```text
PROXY_TYPE=traefik
SSL_MODE=letsencrypt|proxy
TRAEFIK_NETWORK=<existing-overlay>
TRAEFIK_CONSTRAINT_LABEL=<provider-label>
TRAEFIK_CERT_RESOLVER=<resolver-name>
```

### Let's Encrypt mode

Select `letsencrypt` when Traefik directly owns TLS certificates. The declared
API, WebApp, and optional management-service routers use TLS and the selected
certificate resolver.

Before deployment:

- point all declared public DNS names to the proxy;
- ensure ports required by Traefik are reachable;
- ensure the selected certificate resolver exists in the Traefik
  configuration; and
- verify that the selected overlay network is attached to Traefik.

### Upstream proxy mode

Select `proxy` when TLS terminates before this Traefik instance, for example at
an edge proxy, load balancer, or CDN. The generated routers use the profile's
upstream-termination behavior and do not ask this stack to obtain certificates.

Ensure the upstream proxy forwards the original host and HTTPS scheme
correctly and that traffic can reach this Traefik instance.

## Direct published ports

Choose **None (direct port)** when Traefik is not used for this deployment.
The wizard asks for the applicable API, WebApp, and optional management-service
published ports.

The generated `.env` contains:

```text
PROXY_TYPE=none
API_PUBLISHED_PORT=<port>
WEB_PUBLISHED_PORT=<port>          # when a WebApp is enabled
PGADMIN_PUBLISHED_PORT=<port>      # when pgAdmin is enabled
```

Check host/firewall availability before deploying. If another reverse proxy is
used, configure it separately to forward to these published ports.

## Changing routing later

Re-run the same setup wizard and choose the interactive path. Existing `.env`
values are offered as defaults.

After reviewing the regenerated stack:

1. choose **Rebuild swarm stack** if needed;
2. require the Compose check to pass;
3. deploy through the common **Deploy to Docker Swarm** action; and
4. verify common status and public health checks.

Do not remove the stack merely to change proxy mode. An in-place
`docker stack deploy` preserves Swarm's previous service specifications for
rollback.

## Troubleshooting

### Domain does not route

- Confirm the selected public domain in `.env`.
- Confirm DNS reaches the proxy.
- Inspect the rendered router labels in `swarm-stack.yml`.
- Confirm Traefik is attached to `TRAEFIK_NETWORK`.
- Confirm `TRAEFIK_CONSTRAINT_LABEL` matches the Traefik provider constraint;
  do not assume it equals the overlay-network name.
- Inspect Traefik and selected-stack service logs through their normal
  operations menus.

### Certificate is not issued

- Confirm `SSL_MODE=letsencrypt`.
- Confirm `TRAEFIK_CERT_RESOLVER` exactly matches a resolver configured in
  Traefik.
- Confirm DNS and external port reachability.
- Check Traefik certificate resolver logs.

### Redirect loop behind an upstream proxy

- Confirm `SSL_MODE=proxy`.
- Confirm the upstream forwards the original scheme and host.
- Avoid configuring both layers to force incompatible HTTP/HTTPS redirects.

### Direct port is unreachable

- Confirm `PROXY_TYPE=none`.
- Confirm the rendered service publishes the selected port.
- Check the host firewall and whether another service already owns that port.
- Check service convergence and health from the common menu.
