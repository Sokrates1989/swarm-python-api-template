# Proxy Configuration Guide

This guide explains the proxy options available in the Swarm Python API Template and how to choose the right one for your deployment.

## Available Proxy Options

### 1. Traefik (Recommended for Production)

**Best for:**
- Production deployments
- Automatic HTTPS with Let's Encrypt
- Multiple services on the same server
- Domain-based routing

**Features:**
- Automatic SSL certificate generation and renewal
- Domain-based routing (e.g., `api.example.com`)
- Load balancing across replicas
- Automatic service discovery
- HTTP to HTTPS redirection

**Requirements:**
- A domain or subdomain pointing to your swarm manager
- Traefik already deployed on your swarm (external network `traefik`)
- DNS properly configured

**Configuration Files:**
- `.env.postgres.traefik.template` or `.env.neo4j.traefik.template`
- `swarm-stack.postgres.traefik.yml.template` or `swarm-stack.neo4j.traefik.yml.template`

**Access:**
- API accessible at: `https://your-domain.com`

---

### 2. No Proxy (Direct Port Exposure)

**Best for:**
- Development environments
- Custom proxy setups (nginx, HAProxy, Caddy, etc.)
- Single-service deployments
- Testing and staging environments

**Features:**
- Direct port mapping to host
- No external dependencies
- Full control over your own proxy configuration
- Simpler setup for development

**Requirements:**
- Port must be available on the host
- Firewall rules to allow traffic on the chosen port
- You manage your own SSL/TLS if needed

**Configuration Files:**
- `.env.postgres.no-proxy.template` or `.env.neo4j.no-proxy.template`
- `swarm-stack.postgres.no-proxy.yml.template` or `swarm-stack.neo4j.no-proxy.yml.template`

**Access:**
- API accessible at: `http://<server-ip>:<port>`

---

## Choosing the Right Option

### Use Traefik if:
- ✅ You want automatic HTTPS with Let's Encrypt
- ✅ You have a domain pointing to your server
- ✅ You're deploying to production
- ✅ You want automatic service discovery
- ✅ You're running multiple services on the same server

### Use No Proxy if:
- ✅ You're developing or testing locally
- ✅ You already have a reverse proxy (nginx, HAProxy, etc.)
- ✅ You want full control over SSL/TLS configuration
- ✅ You're deploying a single service
- ✅ You don't have a domain or don't need HTTPS

---

## Setup Instructions

### Using the Interactive Setup Wizard (Recommended)

Run the quick-start script and follow the prompts:

**Linux/Mac:**
```bash
./quick-start.sh
```

**Windows:**
```powershell
.\quick-start.ps1
```

The wizard will ask you to choose:
1. Database type (PostgreSQL or Neo4j)
2. **Proxy type (Traefik or no-proxy)**
3. Database mode (local or external)
4. Other configuration options

### Manual Setup

#### For Traefik Setup:

1. **Copy templates:**
   ```bash
   # PostgreSQL with Traefik
   cp setup/.env.postgres.traefik.template .env
   cp setup/swarm-stack.postgres.traefik.yml.template swarm-stack.yml
   
   # OR Neo4j with Traefik
   cp setup/.env.neo4j.traefik.template .env
   cp setup/swarm-stack.neo4j.traefik.yml.template swarm-stack.yml
   ```

2. **Edit .env:**
   - Set `API_URL` to your domain (e.g., `api.example.com`)
   - Configure other variables as needed

3. **Ensure Traefik is running:**
   ```bash
   docker network ls | grep traefik
   ```

4. **Deploy:**
   ```bash
   docker stack deploy -c swarm-stack.yml <STACK_NAME>
   ```

#### For No-Proxy Setup:

1. **Copy templates:**
   ```bash
   # PostgreSQL without proxy
   cp setup/.env.postgres.no-proxy.template .env
   cp setup/swarm-stack.postgres.no-proxy.yml.template swarm-stack.yml
   
   # OR Neo4j without proxy
   cp setup/.env.neo4j.no-proxy.template .env
   cp setup/swarm-stack.neo4j.no-proxy.yml.template swarm-stack.yml
   ```

2. **Edit .env:**
   - Set `PUBLISHED_PORT` to the port you want to expose (default: 8000)
   - Configure other variables as needed

3. **Ensure port is available:**
   ```bash
   # Check if port is in use
   netstat -tuln | grep 8000
   ```

4. **Deploy:**
   ```bash
   docker stack deploy -c swarm-stack.yml <STACK_NAME>
   ```

---

## Using Your Own Proxy with No-Proxy Setup

If you choose the no-proxy option, you can configure your own reverse proxy to handle SSL/TLS and routing.

### Example: nginx Configuration

```nginx
server {
    listen 80;
    server_name api.example.com;
    
    # Redirect HTTP to HTTPS
    return 301 https://$server_name$request_uri;
}

server {
    listen 443 ssl http2;
    server_name api.example.com;
    
    # SSL configuration
    ssl_certificate /etc/ssl/certs/api.example.com.crt;
    ssl_certificate_key /etc/ssl/private/api.example.com.key;
    
    # Proxy to your API
    location / {
        proxy_pass http://localhost:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

### Example: HAProxy Configuration

```haproxy
frontend http_front
    bind *:80
    bind *:443 ssl crt /etc/ssl/certs/api.example.com.pem
    default_backend api_backend

backend api_backend
    balance roundrobin
    server api1 localhost:8000 check
```

---

## Switching Between Proxy Types

To switch from one proxy type to another:

1. **Remove current deployment:**
   ```bash
   docker stack rm <STACK_NAME>
   ```

2. **Copy new templates:**
   ```bash
   # Switch to Traefik
   cp setup/.env.postgres.traefik.template .env
   cp setup/swarm-stack.postgres.traefik.yml.template swarm-stack.yml
   
   # OR switch to no-proxy
   cp setup/.env.postgres.no-proxy.template .env
   cp setup/swarm-stack.postgres.no-proxy.yml.template swarm-stack.yml
   ```

3. **Update configuration:**
   - Edit `.env` with appropriate settings
   - Update secret names in `swarm-stack.yml`

4. **Redeploy:**
   ```bash
   docker stack deploy -c swarm-stack.yml <STACK_NAME>
   ```

---

## Troubleshooting

### Traefik Setup Issues

**Problem:** API not accessible via domain
- Check DNS: `nslookup api.example.com`
- Verify Traefik network exists: `docker network ls | grep traefik`
- Check Traefik logs: `docker service logs traefik_traefik`
- Verify labels in swarm-stack.yml

**Problem:** SSL certificate not generated
- Check Traefik configuration for Let's Encrypt
- Verify domain points to correct IP
- Check Traefik logs for certificate errors

### No-Proxy Setup Issues

**Problem:** Port already in use
- Check what's using the port: `netstat -tuln | grep <PORT>`
- Choose a different port in `.env`
- Redeploy the stack

**Problem:** Cannot access API from external network
- Check firewall rules: `sudo ufw status`
- Verify port is published: `docker service inspect <STACK_NAME>_api`
- Check if service is running: `docker service ps <STACK_NAME>_api`

---

## Additional Resources

- [Traefik Documentation](https://doc.traefik.io/traefik/)
- [Docker Swarm Networking](https://docs.docker.com/engine/swarm/networking/)
- [Let's Encrypt](https://letsencrypt.org/)
- [nginx Reverse Proxy Guide](https://docs.nginx.com/nginx/admin-guide/web-server/reverse-proxy/)
