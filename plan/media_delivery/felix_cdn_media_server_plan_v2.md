# Felix CDN Media Server Plan

## 1. Purpose

This document describes the server-side media delivery setup for Felix reward media.

The current goal is to create a dedicated self-hosted CDN-style media system using Nginx and Docker.

The updated current decision is:

```text
Create a 302 redirector at media.fe-wi.com.
Create the first concrete media delivery node at media1.fe-wi.com.
Use a separate baked Nginx media image for the delivery node.
Serve public static media files.
Use versioned immutable media paths.
Do not proxy media bytes through the redirector.
```

The term `CDN Media Server` is used here because this setup acts as the current media origin and already follows a mini CDN-style pattern:

```text
stable public entrypoint
  ↓
redirector
  ↓
delivery node
```

---

## 2. Related Documents

The App-side implementation is defined here:

- [App Media Integration Plan](./felix_app_media_integration_plan_v2.md)

The overall purpose and decision summary are defined here:

- [Felix Media Delivery Plan Overview](./felix_media_delivery_overview_v2.md)

---

## 3. Current Server Architecture

Current architecture:

```text
https://media.fe-wi.com
  ↓
Nginx Redirector
  ↓
302 Location: https://media1.fe-wi.com/<same-path>
  ↓
Nginx CDN Media Delivery Node
  ↓
Static media files baked into Docker image.
```

The redirector and media delivery node can run on the same physical server at the beginning.

They should still be separated logically:

```text
media.fe-wi.com:
  redirector service

media1.fe-wi.com:
  static media delivery service
```

This makes the next step easier because `media2.fe-wi.com` and `media3.fe-wi.com` can later be added without changing the App URLs.

---

## 4. Server Responsibilities

### 4.1 Redirector responsibilities.

The redirector is responsible for:

```text
- Receiving stable public media requests.
- Preserving the request path.
- Selecting a delivery node.
- Returning a temporary redirect.
- Not streaming or proxying media bytes.
```

In Phase 1, selection is simple:

```text
always redirect to https://media1.fe-wi.com
```

### 4.2 Delivery node responsibilities.

The delivery node is responsible for:

```text
- Serving static media files.
- Returning 404 for missing files.
- Providing correct MIME handling.
- Supporting video/audio byte range requests.
- Sending cache headers.
- Sending CORS headers.
- Serving immutable versioned media paths.
- Being reproducibly deployable through Docker image tags.
```

### 4.3 Backend responsibilities related to media issues.

The backend is responsible for:

```text
- Receiving media issue reports from the App.
- Deduplicating repeated issue reports.
- Throttling admin notifications.
- Sending Telegram and/or email notifications to admins.
```

The backend does not stream media files in the current approach.

---

## 5. Domain Strategy

Current domains:

```text
https://media.fe-wi.com
https://media1.fe-wi.com
```

Meaning:

```text
media.fe-wi.com:
  Stable App-facing entrypoint and redirector.

media1.fe-wi.com:
  First concrete media delivery node.
```

Future possible delivery node domains:

```text
https://media2.fe-wi.com
https://media3.fe-wi.com
```

Future possible regional entrypoints:

```text
https://media.eu.fe-wi.com
https://media.us.fe-wi.com
https://media.asia.fe-wi.com
```

---

## 6. Public URL Structure

The App-facing URL structure is:

```text
https://media.fe-wi.com/felix/rewards/<rewardId>/<version>/<locale>/<file>
```

Examples:

```text
https://media.fe-wi.com/felix/rewards/thoughts-feelings-actions/v1/de/poster.png
https://media.fe-wi.com/felix/rewards/thoughts-feelings-actions/v1/de/video-720p.mp4
https://media.fe-wi.com/felix/rewards/thoughts-feelings-actions/v1/de/audio-128.mp3
https://media.fe-wi.com/felix/rewards/thoughts-feelings-actions/v1/de/captions.vtt
```

The redirect target is:

```text
https://media1.fe-wi.com/felix/rewards/<rewardId>/<version>/<locale>/<file>
```

Example redirect:

```text
302 Location: https://media1.fe-wi.com/felix/rewards/thoughts-feelings-actions/v1/de/video-720p.mp4
```

The delivery node URL structure must be identical after the host.

---

## 7. Versioning And Caching Strategy

Use versioned folders:

```text
/v1/
/v2/
/v3/
```

Rule:

```text
Never overwrite files inside an existing version folder.
```

If content changes:

```text
1. Create a new version folder.
2. Upload or bake the new files.
3. Update the App manifest to reference the new version.
```

This allows long cache lifetimes for media files.

Recommended delivery node media cache header:

```http
Cache-Control: public, max-age=31536000, immutable
```

Recommended JSON cache header:

```http
Cache-Control: public, max-age=300
```

Recommended redirector cache header:

```http
Cache-Control: no-store
```

Reason:

```text
Redirect routing may change later.
The redirect response should not become permanently sticky in browsers or proxies.
```

---

## 8. Media Repository Structure

Recommended repository or folder:

```text
felix-media/
  redirector/
    Dockerfile
    nginx.conf
  delivery-node/
    Dockerfile
    nginx.conf
    media/
      health.txt
      felix/
        rewards/
          thoughts-feelings-actions/
            v1/
              de/
                poster.png
                video-720p.mp4
                audio-128.mp3
                captions.vtt
              en/
                poster.png
                video-720p.mp4
                audio-128.mp3
                captions.vtt
```

Alternative for a simpler first version:

```text
felix-media/
  Dockerfile.redirector
  Dockerfile.delivery-node
  nginx.redirector.conf
  nginx.delivery-node.conf
  media/
    health.txt
    felix/
      rewards/
        thoughts-feelings-actions/
          v1/
            de/
              poster.png
              video-720p.mp4
              audio-128.mp3
              captions.vtt
            en/
              poster.png
              video-720p.mp4
              audio-128.mp3
              captions.vtt
```

The delivery node image copies `media/` into the Nginx web root.

---

## 9. Health Check File

Add:

```text
media/health.txt
```

Content:

```text
ok
```

Expected delivery node URL:

```text
https://media1.fe-wi.com/health.txt
```

Expected redirector URL:

```text
https://media.fe-wi.com/health.txt
```

The redirector may redirect `/health.txt` to `media1.fe-wi.com/health.txt`, or it may serve its own health response.

For future health checks, it is useful if delivery nodes expose their own direct health endpoint.

---

## 10. Docker Image Strategy

Recommended images:

```text
sokrates1989/felix-media-redirector:<version>
sokrates1989/felix-media-node:<version>
```

Examples:

```text
sokrates1989/felix-media-redirector:0.0.1
sokrates1989/felix-media-node:0.0.1
```

Avoid relying on:

```text
latest
```

Use explicit image versions.

This fits the preferred deployment style where image versions are controlled explicitly.

---

## 11. Redirector Dockerfile

Recommended initial redirector Dockerfile:

```dockerfile
FROM nginx:alpine

COPY nginx.conf /etc/nginx/conf.d/default.conf
```

The redirector does not need the media files.

---

## 12. Delivery Node Dockerfile

Recommended initial delivery node Dockerfile:

```dockerfile
FROM nginx:alpine

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY media/ /usr/share/nginx/html/
```

This creates a dedicated static media delivery image.

---

## 13. Redirector Nginx Configuration

Recommended initial redirector `nginx.conf`:

```nginx
server {
    listen 80;
    server_name _;

    location / {
        add_header Cache-Control "no-store" always;
        return 302 https://media1.fe-wi.com$request_uri;
    }
}
```

### Explanation.

```text
return 302 https://media1.fe-wi.com$request_uri;
```

Preserves the complete path and query string.

Example:

```text
https://media.fe-wi.com/felix/rewards/a/v1/de/video-720p.mp4
```

redirects to:

```text
https://media1.fe-wi.com/felix/rewards/a/v1/de/video-720p.mp4
```

### Why 302.

Use:

```text
302 Found
```

or later:

```text
307 Temporary Redirect
```

Avoid:

```text
301 Moved Permanently
```

because browsers may cache permanent redirects too aggressively.

---

## 14. Delivery Node Nginx Configuration

Recommended delivery node `nginx.conf`:

```nginx
server {
    listen 80;
    server_name _;

    root /usr/share/nginx/html;

    include /etc/nginx/mime.types;
    default_type application/octet-stream;

    sendfile on;

    location / {
        try_files $uri =404;

        add_header Access-Control-Allow-Origin "*" always;
        add_header Access-Control-Allow-Methods "GET, HEAD, OPTIONS" always;
        add_header Accept-Ranges bytes always;
    }

    location ~* \.(mp4|mp3|png|jpg|jpeg|webp|vtt)$ {
        try_files $uri =404;

        add_header Cache-Control "public, max-age=31536000, immutable" always;
        add_header Access-Control-Allow-Origin "*" always;
        add_header Access-Control-Allow-Methods "GET, HEAD, OPTIONS" always;
        add_header Accept-Ranges bytes always;
    }

    location ~* \.(json)$ {
        try_files $uri =404;

        add_header Cache-Control "public, max-age=300" always;
        add_header Access-Control-Allow-Origin "*" always;
        add_header Access-Control-Allow-Methods "GET, HEAD, OPTIONS" always;
    }
}
```

### Explanation.

```text
try_files $uri =404;
```

Returns 404 for missing files.

```text
sendfile on;
```

Improves static file serving.

```text
Cache-Control: public, max-age=31536000, immutable
```

Allows aggressive caching for versioned media files.

```text
Access-Control-Allow-Origin: *
```

Allows App/browser access to public media files.

```text
Accept-Ranges: bytes
```

Supports seeking and partial media loading.

---

## 15. Docker Swarm Service Example

Example stack services:

```yaml
services:
  felix_media_redirector:
    image: sokrates1989/felix-media-redirector:0.0.1
    networks:
      - traefik
    deploy:
      replicas: 1
      labels:
        - traefik.enable=true
        - traefik.constraint-label=traefik-public
        - traefik.docker.network=traefik
        - traefik.http.routers.felix-media-redirector.rule=Host(`media.fe-wi.com`)
        - traefik.http.routers.felix-media-redirector.entrypoints=http
        - traefik.http.services.felix-media-redirector.loadbalancer.server.port=80

  felix_media_node_1:
    image: sokrates1989/felix-media-node:0.0.1
    networks:
      - traefik
    deploy:
      replicas: 1
      labels:
        - traefik.enable=true
        - traefik.constraint-label=traefik-public
        - traefik.docker.network=traefik
        - traefik.http.routers.felix-media-node-1.rule=Host(`media1.fe-wi.com`)
        - traefik.http.routers.felix-media-node-1.entrypoints=http
        - traefik.http.services.felix-media-node-1.loadbalancer.server.port=80

networks:
  traefik:
    external: true
```

### Note.

If HTTPS is terminated by Nginx Proxy Manager before traffic reaches Traefik, the `entrypoints=http` approach may be correct.

If Traefik handles HTTPS directly, use the existing HTTPS labels and certificate resolver pattern from the production setup.

---

## 16. DNS And TLS

Create DNS entries for:

```text
media.fe-wi.com
media1.fe-wi.com
```

Possible DNS setup:

```text
A record:
media.fe-wi.com → server IPv4
media1.fe-wi.com → server IPv4

AAAA record:
media.fe-wi.com → server IPv6
media1.fe-wi.com → server IPv6

CNAME:
media.fe-wi.com → existing proxy target
media1.fe-wi.com → existing proxy target
```

TLS must be active for both domains.

Use the same working approach as the existing infrastructure:

```text
- Nginx Proxy Manager certificate, or
- Traefik ACME certificate, or
- wildcard certificate.
```

---

## 17. Media Preparation Requirements

### Video.

Recommended serving file:

```text
video-720p.mp4
```

Recommended format:

```text
MP4 container.
H.264 video.
AAC audio.
720p.
```

Recommended FFmpeg command:

```bash
ffmpeg -i input.mp4 \
  -vf "scale=-2:720" \
  -c:v libx264 \
  -profile:v high \
  -level 4.0 \
  -pix_fmt yuv420p \
  -crf 23 \
  -preset medium \
  -c:a aac \
  -b:a 128k \
  -movflags +faststart \
  video-720p.mp4
```

### Audio.

Recommended serving file:

```text
audio-128.mp3
```

Recommended format:

```text
MP3 44.1 kHz, 128 kbps.
```

Keep WAV files as editable masters outside the serving image if needed.

### Poster.

Recommended serving file:

```text
poster.png
```

### Captions.

Recommended serving file:

```text
captions.vtt
```

Use WebVTT. Convert `.srt` files before serving.

---

## 18. Build Flow

Manual initial build:

```bash
docker build -f redirector/Dockerfile -t sokrates1989/felix-media-redirector:0.0.1 redirector
docker build -f delivery-node/Dockerfile -t sokrates1989/felix-media-node:0.0.1 delivery-node

docker push sokrates1989/felix-media-redirector:0.0.1
docker push sokrates1989/felix-media-node:0.0.1
```

Deploy:

```bash
docker stack deploy -c docker-compose.yml felix_media
```

Or update existing services:

```bash
docker service update --image sokrates1989/felix-media-redirector:0.0.1 <redirector-service-name>
docker service update --image sokrates1989/felix-media-node:0.0.1 <node-service-name>
```

---

## 19. Recommended CI/CD Flow

Later, automate:

```text
1. Commit new media files.
2. Build delivery node image.
3. Build redirector image if redirector config changed.
4. Tag images with explicit versions.
5. Push images to registry.
6. Deploy to production.
7. Run smoke tests.
```

Recommended release notes:

```text
- redirector image version
- media node image version
- added reward IDs
- changed media versions
- removed media versions
- known compatibility notes
```

---

## 20. Server Testing Checklist

### Redirector health.

```bash
curl -I https://media.fe-wi.com/health.txt
```

Expected:

```text
HTTP 302
Location: https://media1.fe-wi.com/health.txt
```

or, if the redirector serves its own health response:

```text
HTTP 200
```

### Delivery node health.

```bash
curl -I https://media1.fe-wi.com/health.txt
```

Expected:

```text
HTTP 200
```

### Redirect behavior.

```bash
curl -I https://media.fe-wi.com/felix/rewards/thoughts-feelings-actions/v1/de/video-720p.mp4
```

Expected:

```text
HTTP 302
Location: https://media1.fe-wi.com/felix/rewards/thoughts-feelings-actions/v1/de/video-720p.mp4
Cache-Control: no-store
```

### Follow redirect.

```bash
curl -IL https://media.fe-wi.com/felix/rewards/thoughts-feelings-actions/v1/de/video-720p.mp4
```

Expected:

```text
HTTP 302
HTTP 200
Content-Type: video/mp4
```

### Delivery node video file.

```bash
curl -I https://media1.fe-wi.com/felix/rewards/thoughts-feelings-actions/v1/de/video-720p.mp4
```

Expected:

```text
HTTP 200
Content-Type: video/mp4
Cache-Control: public, max-age=31536000, immutable
Accept-Ranges: bytes
```

### Audio file.

```bash
curl -I https://media1.fe-wi.com/felix/rewards/thoughts-feelings-actions/v1/de/audio-128.mp3
```

Expected:

```text
HTTP 200
Content-Type: audio/mpeg
```

### Captions file.

```bash
curl -I https://media1.fe-wi.com/felix/rewards/thoughts-feelings-actions/v1/de/captions.vtt
```

Expected:

```text
HTTP 200
Content-Type: text/vtt
```

### Missing file.

```bash
curl -IL https://media.fe-wi.com/felix/rewards/missing/v1/de/video-720p.mp4
```

Expected:

```text
HTTP 302
HTTP 404
```

### Range request.

```bash
curl -I -H "Range: bytes=0-1023" https://media1.fe-wi.com/felix/rewards/thoughts-feelings-actions/v1/de/video-720p.mp4
```

Expected:

```text
HTTP 206 Partial Content
```

If this does not return 206, verify actual browser/app playback and Nginx range behavior.

---

## 21. Backend Media Issue Reporting

The backend route is not part of the CDN Media Server, but it is part of the complete media delivery reliability workflow.

Recommended route:

```text
POST /api/media/report-issue
```

Purpose:

```text
The App reports media delivery problems detected through lightweight background checks or playback failures.
```

Backend notification channels:

```text
- Telegram.
- Email.
```

Backend requirements:

```text
- validate payload
- deduplicate repeated reports
- throttle notifications
- notify admins
- return success to the App
```

The backend must not stream the media files in this approach.

---

## 22. Logging And Privacy

Media files are public, but access logs may contain IP addresses.

Recommended:

```text
- Keep access logs minimal.
- Rotate logs.
- Avoid query parameters containing user data.
- Do not put user IDs into media URLs.
- Do not put email addresses into media URLs.
- Do not put tokens into media URLs.
```

The setup avoids adding an external CDN provider for now.

The server/hosting provider remains relevant for technical request processing.

---

## 23. Current Security Position

The media files are public.

This means:

```text
Anyone with the direct URL can access the file.
Anyone can follow the redirect to media1.fe-wi.com.
```

This is accepted for now because the media is informational reward content.

The reward unlock logic remains in the App/backend UX flow.

Do not treat public media URLs as protected assets.

---

## 24. Rollback Strategy

Rollback is handled through Docker image tags.

Example current delivery node version:

```text
sokrates1989/felix-media-node:0.0.2
```

Rollback to:

```text
sokrates1989/felix-media-node:0.0.1
```

Important:

```text
- Keep older image tags available.
- Keep older media version paths available while any App version may reference them.
- Do not delete /v1/ just because /v2/ exists.
```

Redirector rollback is separate:

```text
sokrates1989/felix-media-redirector:0.0.1
```

---

## 25. Future Plan: Multiple Delivery Nodes

Future shape:

```text
media.fe-wi.com
  ↓
302 redirector
  ↓
media1.fe-wi.com
media2.fe-wi.com
media3.fe-wi.com
```

Each media node runs the same image:

```text
sokrates1989/felix-media-node:1.0.0
```

Each node has the same URL path structure.

Example direct node URLs:

```text
https://media1.fe-wi.com/felix/rewards/thoughts-feelings-actions/v1/de/video-720p.mp4
https://media2.fe-wi.com/felix/rewards/thoughts-feelings-actions/v1/de/video-720p.mp4
https://media3.fe-wi.com/felix/rewards/thoughts-feelings-actions/v1/de/video-720p.mp4
```

---

## 26. Future Plan: Smarter 302 Redirector

The redirector prevents a central proxy bottleneck.

### Bad future model.

```text
User
  ↓
central load balancer
  ↓
media node
```

If the central load balancer proxies video bytes, it becomes a bottleneck.

### Better future model.

```text
User
  ↓
media.fe-wi.com
  ↓
302 Location: https://media2.fe-wi.com/felix/rewards/...
  ↓
User downloads directly from media2.fe-wi.com
```

The redirector only sends tiny redirect responses.

The selected media node sends the actual video/audio bytes.

### Future redirector responsibilities.

```text
- Know available media nodes.
- Check health of each node.
- Select a healthy node.
- Return 302 or 307 temporary redirect.
- Avoid unhealthy nodes.
- Optionally use sticky selection for a user/session/device.
- Optionally use weighted distribution.
```

### Recommended status code.

Use:

```text
302 Found
```

or:

```text
307 Temporary Redirect
```

Avoid:

```text
301 Moved Permanently
```

because browsers may cache permanent redirects aggressively.

---

## 27. Future Plan: Regional Expansion

If Felix expands outside the EU, add regional media entrypoints.

Example:

```text
https://media.eu.fe-wi.com
https://media.us.fe-wi.com
https://media.asia.fe-wi.com
```

Possible future architecture:

```text
media.eu.fe-wi.com
  ↓
EU redirector
  ↓
eu1.media.fe-wi.com
eu2.media.fe-wi.com

media.us.fe-wi.com
  ↓
US redirector
  ↓
us1.media.fe-wi.com
us2.media.fe-wi.com
```

Possible App config later:

```json
{
  "mediaRegions": {
    "eu": "https://media.eu.fe-wi.com",
    "us": "https://media.us.fe-wi.com",
    "asia": "https://media.asia.fe-wi.com"
  },
  "defaultMediaRegion": "eu"
}
```

Recommended future approach:

```text
Backend or app config returns the recommended mediaBaseUrl.
The App uses that mediaBaseUrl for all media requests.
```

User-selected region is also possible:

```text
Media delivery region:
- Europe
- United States
- Automatic
```

Do not implement this now.

---

## 28. Future Plan: External CDN

If traffic grows heavily, a real CDN can be placed in front of the existing media domain.

Future shape:

```text
media.fe-wi.com
  ↓
External CDN/cache
  ↓
Felix redirector or media origin
```

The App does not need to change if the public URL remains stable.

---

## 29. Server Implementation Prompt For Codex

```text
Create a self-hosted CDN-style media delivery setup for Felix reward media.

Current decision:
- Use media.fe-wi.com as the stable App-facing media entrypoint.
- Use a 302 redirector at media.fe-wi.com.
- Use media1.fe-wi.com as the first concrete delivery node.
- The redirector and delivery node may run on the same physical server.
- Do not proxy media bytes through the redirector.
- Do not put media files into the App image.
- Do not implement Cloudflare R2.
- Do not implement external CDN.
- Do not implement signed URLs.
- Do not implement HLS.
- Do not implement backend media streaming.

Expected App-facing URL structure:
https://media.fe-wi.com/felix/rewards/<rewardId>/<version>/<locale>/<file>

Expected delivery node URL structure:
https://media1.fe-wi.com/felix/rewards/<rewardId>/<version>/<locale>/<file>

Example:
https://media.fe-wi.com/felix/rewards/thoughts-feelings-actions/v1/de/video-720p.mp4
redirects to:
https://media1.fe-wi.com/felix/rewards/thoughts-feelings-actions/v1/de/video-720p.mp4

Create:
- redirector Dockerfile
- redirector nginx.conf
- delivery node Dockerfile
- delivery node nginx.conf
- media folder structure
- media/health.txt
- Docker Swarm service example for Traefik
- README with build, push and deploy commands

Redirector requirements:
- listen on port 80
- preserve full request URI
- return 302 to https://media1.fe-wi.com$request_uri
- set Cache-Control: no-store
- do not serve media files
- do not proxy media files

Delivery node requirements:
- serve static files from /usr/share/nginx/html
- return 404 for missing files
- include MIME types
- enable sendfile
- support video/audio range requests
- set Cache-Control: public, max-age=31536000, immutable for media files
- set Cache-Control: public, max-age=300 for JSON files
- add CORS headers for GET and HEAD
- serve health.txt for monitoring

Media structure:
media/
  health.txt
  felix/
    rewards/
      thoughts-feelings-actions/
        v1/
          de/
            poster.png
            video-720p.mp4
            audio-128.mp3
            captions.vtt
          en/
            poster.png
            video-720p.mp4
            audio-128.mp3
            captions.vtt

Use explicit Docker image tags, not latest.

Keep the implementation open for future delivery nodes:
media2.fe-wi.com
media3.fe-wi.com

Do not implement the smart multi-node redirector yet.
For now, redirect every request to media1.fe-wi.com.
```

---

## 30. Backend Notification Prompt For Codex

```text
Implement backend support for media delivery issue notifications.

Create:
POST /api/media/report-issue

Purpose:
The App calls this route when a lightweight media availability check fails or when media playback fails due to a likely delivery issue.

Request payload should include:
- rewardId
- version
- locale
- mediaType
- mediaUrl
- statusCode if available
- errorType
- source
- appVersion if available
- checkedAt if available

Do not require sensitive user information for this route.
Do not stream media files from this route.

Backend behavior:
- validate payload
- normalize issue key using rewardId + version + locale + mediaType + statusCode + errorType
- deduplicate repeated issues
- throttle admin notifications for the same issue key
- optionally store issue event if persistence exists
- send Telegram message to admins if configured
- send email message to admins if configured
- return { "ok": true } to the App

Recommended throttling:
Do not notify more than once per issue key within 30 to 60 minutes.

The route only reports delivery issues to admins.
```

---

## 31. Final Server Decision

The server-side implementation should be:

```text
302 redirector at media.fe-wi.com.
First delivery node at media1.fe-wi.com.
Dedicated Nginx CDN Media Delivery Node image.
Media files baked into the delivery node image.
Versioned immutable media paths.
Long cache headers for media.
Short cache headers for JSON.
No-store cache header for redirect responses.
Simple Docker Swarm deployment.
No external media provider.
No protected media API.
Future-compatible with media2/media3 delivery nodes and regional expansion.
```
