# SSL/TLS Configuration Options

The shared setup dialogue supports two TLS ownership modes for public profiles
that allow Traefik. The selected site config or existing root `.env` supplies
the displayed default.

## Configuration Modes

### 1. Let's Encrypt (Traefik-owned TLS)
**When to use:** Traefik directly faces the internet and handles SSL/TLS termination.

**Characteristics:**
- Traefik obtains SSL certificates from Let's Encrypt
- Certificates are automatically renewed
- Direct HTTPS connections to Traefik
- Entrypoints: `https`, `http`, `web`
- TLS enabled with cert resolver

**Traefik Labels:**
```yaml
- traefik.http.routers.${STACK_NAME}_api.entrypoints=https,http,web
- traefik.http.routers.${STACK_NAME}_api.tls=true
- traefik.http.routers.${STACK_NAME}_api.tls.certresolver=le
```

**Use cases:**
- Direct deployment on VPS/dedicated server
- Traefik is the edge proxy
- No CDN or upstream proxy

---

### 2. Proxy SSL
**When to use:** SSL is terminated at an upstream proxy (e.g., Cloudflare, nginx, another Traefik instance).

**Characteristics:**
- Traefik receives HTTP traffic from upstream proxy
- SSL already terminated before reaching Traefik
- Uses `X-Forwarded-Proto` header to indicate HTTPS
- Entrypoints: `http` only
- No TLS configuration in Traefik

**Traefik Labels:**
```yaml
- traefik.http.routers.${STACK_NAME}_api.entrypoints=http
- traefik.http.middlewares.${STACK_NAME}_protoheader.headers.customrequestheaders.X-Forwarded-Proto=https
- traefik.http.routers.${STACK_NAME}_api.middlewares=${STACK_NAME}_protoheader
```

**Use cases:**
- Behind Cloudflare (SSL/TLS mode: Full or Flexible)
- Behind another reverse proxy handling SSL
- Behind a load balancer with SSL termination
- Multi-tier proxy architecture

---

## Comparison

| Feature | Direct SSL | Proxy SSL |
|---------|-----------|-----------|
| **SSL Termination** | Traefik | Upstream Proxy |
| **Certificates** | Let's Encrypt (auto) | Managed upstream |
| **Traefik Entrypoint** | https, http, web | http |
| **TLS Config** | Yes | No |
| **X-Forwarded-Proto** | Not needed | Required |
| **Complexity** | Lower | Higher (multi-tier) |

---

## Common Scenarios

### Scenario 1: Direct VPS Deployment
```
Internet → Traefik → API
         (SSL here)
```
**Choose:** Let's Encrypt

### Scenario 2: Behind Cloudflare
```
Internet → Cloudflare → Traefik → API
         (SSL here)   (HTTP)
```
**Choose:** Proxy SSL

### Scenario 3: Behind nginx
```
Internet → nginx → Traefik → API
         (SSL here) (HTTP)
```
**Choose:** Proxy SSL

### Scenario 4: Multi-Swarm Setup
```
Internet → Edge Traefik → Internal Traefik → API
         (SSL here)      (HTTP)
```
**Choose:** Proxy SSL (for internal Traefik)

---

## Troubleshooting

### Issue: "Too Many Redirects" with Cloudflare
**Cause:** Cloudflare SSL mode set to "Flexible" with Traefik-owned TLS.
**Solution:** 
- Use Proxy SSL configuration, OR
- Set Cloudflare SSL mode to "Full" or "Full (strict)"

### Issue: "Connection Not Secure" Warning
**Cause:** Using Let's Encrypt mode but the certificate authority cannot reach
your Traefik service.
**Solution:**
- Ensure ports 80 and 443 are open
- Check DNS points to your server
- Verify Traefik is running and accessible

### Issue: Application Shows HTTP Instead of HTTPS
**Cause:** Using Proxy SSL but `X-Forwarded-Proto` not set correctly.
**Solution:**
- Verify middleware is applied
- Check upstream proxy sets `X-Forwarded-Proto: https` header
- Ensure application respects the header

---

## Setup Wizard Flow

When you run the setup wizard:

1. **Select Proxy Type:** Choose "Traefik"
2. **Select SSL Mode:**
   - **Option 1:** Let's Encrypt (Traefik owns certificates)
   - **Option 2:** Proxy SSL (SSL terminated at upstream proxy)

The wizard will automatically:
- retain the selection in root `.env`
- route rendering through the selected profile adapter
- Configure entrypoints correctly
- Add or omit TLS configuration
- Set up middleware if needed

---

## Renderer implementation

Version-3 compatibility rendering uses shared label snippets:

```
setup/compose-modules/snippets/
├── proxy-traefik-direct-ssl.labels.yml    # Direct SSL labels
└── proxy-traefik-proxy-ssl.labels.yml     # Proxy SSL labels
```

Version-5 executable rendering emits the equivalent labels through the shared
deterministic renderer. These are renderer details only; both formats use the
same numbered setup section.

---

## Migration

### From Let's Encrypt to Proxy SSL
1. Run setup wizard again
2. Select "Proxy SSL" mode
3. Review the rendered stack and redeploy it in place

### From Proxy SSL to Let's Encrypt
1. Ensure Traefik can obtain Let's Encrypt certificates
2. Run setup wizard again
3. Select "Let's Encrypt" mode
4. Review the rendered stack and redeploy it in place

---

## Best Practices

1. **Use Traefik-owned TLS when appropriate** - Confirm DNS, external
   reachability, and the selected certificate resolver
2. **Use Proxy SSL when required** - Behind CDN, load balancer, or multi-tier setup
3. **Document your choice** - Note which mode you're using for future reference
4. **Test after deployment** - Verify SSL works correctly in browser
5. **Monitor certificates** - Ensure Let's Encrypt renewals work (Direct SSL only)

---

## References

- [Traefik HTTPS Documentation](https://doc.traefik.io/traefik/https/overview/)
- [Traefik Let's Encrypt](https://doc.traefik.io/traefik/https/acme/)
- [X-Forwarded-Proto Header](https://developer.mozilla.org/en-US/docs/Web/HTTP/Headers/X-Forwarded-Proto)
- [Cloudflare SSL Modes](https://developers.cloudflare.com/ssl/origin-configuration/ssl-modes/)
