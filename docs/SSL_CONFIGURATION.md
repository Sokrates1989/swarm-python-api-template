# SSL/TLS Configuration Options

The setup wizard now supports two different SSL/TLS configurations for Traefik deployments.

## Configuration Modes

### 1. Direct SSL (Default)
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
**Choose:** Direct SSL

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
**Cause:** Cloudflare SSL mode set to "Flexible" with Direct SSL configuration.
**Solution:** 
- Use Proxy SSL configuration, OR
- Set Cloudflare SSL mode to "Full" or "Full (strict)"

### Issue: "Connection Not Secure" Warning
**Cause:** Using Direct SSL but Let's Encrypt can't reach your server.
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
   - **Option 1:** Direct SSL (Traefik handles SSL with Let's Encrypt)
   - **Option 2:** Proxy SSL (SSL terminated at upstream proxy)

The wizard will automatically:
- Select the appropriate Traefik label snippet
- Configure entrypoints correctly
- Add or omit TLS configuration
- Set up middleware if needed

---

## File Structure

The SSL configuration is implemented through separate snippet files:

```
setup/compose-modules/snippets/
├── proxy-traefik-direct-ssl.labels.yml    # Direct SSL labels
└── proxy-traefik-proxy-ssl.labels.yml     # Proxy SSL labels
```

The wizard selects the appropriate file based on your choice.

---

## Migration

### From Direct SSL to Proxy SSL
1. Run setup wizard again
2. Select "Proxy SSL" mode
3. Redeploy stack

### From Proxy SSL to Direct SSL
1. Ensure Traefik can obtain Let's Encrypt certificates
2. Run setup wizard again
3. Select "Direct SSL" mode
4. Redeploy stack

---

## Best Practices

1. **Use Direct SSL when possible** - Simpler configuration, fewer moving parts
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
