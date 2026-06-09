# Felix Media Delivery Plan Overview

## 1. Main Purpose

This document explains the current Felix media delivery approach at a high level and links to the two detailed implementation plans:

- [App Media Integration Plan](./felix_app_media_integration_plan_v2.md)
- [CDN Media Server Plan](./felix_cdn_media_server_plan_v2.md)

The purpose is to support audio and video reward playback in the Felix App with a setup that is simple enough for the current web-app mock-up, but structured enough to evolve later.

The updated current decision is:

```text
Use a dedicated Dockerized Nginx CDN Media Server with baked-in static media files.
Use a 302 redirector from the beginning.
Expose the stable public entry domain as media.fe-wi.com.
Redirect media requests to the first delivery node media1.fe-wi.com.
Use lazy playback in the App.
Use lightweight media availability checks before showing media controls.
Report broken/missing media issues to the backend.
Notify admins through Telegram and/or email.
Do not use Cloudflare R2, external CDN, HLS, signed URLs or protected API media delivery for now.
```

The media content is currently informational reward content. It does not need strict access protection. The App controls when a reward is shown or unlocked, while the media files themselves are delivered as public static assets.

---

## 2. Document Map

### 2.1 App Media Integration Plan

Use this document when implementing the App-side logic.

File:

```text
felix_app_media_integration_plan_v2.md
```

It covers:

```text
- App configuration strategy.
- mediaBaseUrl handling.
- Reward media manifest shape.
- Relative media paths.
- Final URL construction.
- Lightweight media availability checks.
- Background media validation when opening a reward.
- Hiding media sections until validation succeeds.
- Backend issue reporting route.
- Admin notification expectations.
- Lazy playback behavior.
- Poster, audio, video and captions usage.
- Error handling.
- App-side testing checklist.
```

### 2.2 CDN Media Server Plan

Use this document when implementing the server-side media delivery setup.

File:

```text
felix_cdn_media_server_plan_v2.md
```

It covers:

```text
- Dedicated Nginx media image.
- 302 redirector from media.fe-wi.com to media1.fe-wi.com.
- First delivery node media1.fe-wi.com.
- Baked media file structure.
- Dockerfile.
- Nginx configuration for redirector.
- Nginx configuration for delivery node.
- Docker Swarm / Traefik service examples.
- Domain strategy.
- Caching headers.
- CORS.
- Testing with curl.
- Deployment strategy.
- Future multi-node plan.
- Future regional expansion plan.
```

---

## 3. Current Architecture

The current planned architecture is:

```text
App
  ↓
mediaBaseUrl + relative media path
  ↓
https://media.fe-wi.com/felix/rewards/...
  ↓
302 Redirector
  ↓
https://media1.fe-wi.com/felix/rewards/...
  ↓
Nginx CDN Media Delivery Node
  ↓
Static media files baked into the Docker image.
```

The App does not bundle the media files.

The App stores or receives metadata and paths only.

The CDN Media Server stores the actual media files.

The redirector and the first delivery node can run on the same physical server at the beginning. They are separated logically by domain and service role.

---

## 4. Why This Approach Was Chosen

This approach is closer to the future target structure while still requiring only one delivery server at the beginning.

### 4.1 Advantages.

```text
- Stable public media entrypoint from day one: media.fe-wi.com.
- First delivery node from day one: media1.fe-wi.com.
- Future media2/media3 nodes can be added without changing App URLs.
- Redirector avoids a future central media-byte bottleneck.
- Redirector can start simple because only one delivery node exists initially.
- No external media delivery provider is needed.
- No Cloudflare R2 setup is needed.
- No object storage is needed.
- No protected media API is needed.
- No HLS/adaptive streaming is needed.
- No signed URL system is needed.
- Media can be deployed reproducibly as a Docker image.
- Media can be rolled back through Docker image tags.
- The App can lazy-load media only when needed.
- The App can verify media availability before showing media controls.
```

### 4.2 Trade-offs.

```text
- Media URLs are public after redirect.
- Anyone with the direct node URL can access the file.
- This is not DRM.
- This does not enforce reward unlocks at the media server level.
- The redirector adds one HTTP round-trip before media delivery.
- The redirector must be highly available if it becomes critical.
- One delivery node does not equal CDN-grade scaling.
```

For Felix informational reward media, this trade-off is acceptable.

---

## 5. Responsibility Split

The architecture is intentionally split into clear responsibilities.

### 5.1 App responsibility.

The App is responsible for:

```text
- Knowing which reward exists.
- Knowing whether a reward should appear unlocked.
- Showing reward metadata.
- Constructing media URLs.
- Running lightweight availability checks when useful.
- Hiding media controls when validation fails.
- Calling a backend issue-reporting route if media is unavailable.
- Starting playback only after user action.
- Handling loading and playback errors.
- Releasing media resources when no longer needed.
```

The App is not responsible for storing binary media files.

### 5.2 Backend responsibility.

The backend is responsible for:

```text
- Receiving media issue reports from the App.
- Deduplicating or throttling repeated issue reports.
- Notifying admins through Telegram and/or email.
- Optionally storing issue events for later review.
```

The backend is not responsible for streaming media files in the current approach.

### 5.3 Redirector responsibility.

The redirector is responsible for:

```text
- Receiving stable public media requests at media.fe-wi.com.
- Selecting a delivery node.
- Returning a 302 or 307 redirect to the selected delivery node.
- Avoiding proxying media bytes.
```

In Phase 1, the redirector can always redirect to:

```text
https://media1.fe-wi.com
```

### 5.4 CDN Media Delivery Node responsibility.

The delivery node is responsible for:

```text
- Serving static files.
- Returning 404 for missing files.
- Serving correct MIME types.
- Sending cache headers.
- Supporting media range requests.
- Hosting versioned media paths.
- Being deployable as a dedicated Docker image.
```

The delivery node is not responsible for authentication, reward unlocking or user-specific logic.

---

## 6. Current Domain Strategy

The current domains should be:

```text
https://media.fe-wi.com
https://media1.fe-wi.com
```

Meaning:

```text
media.fe-wi.com:
  stable public entrypoint and redirector.

media1.fe-wi.com:
  first concrete delivery node.
```

Future domains could be:

```text
https://media2.fe-wi.com
https://media3.fe-wi.com
https://media.eu.fe-wi.com
https://media.us.fe-wi.com
https://media.asia.fe-wi.com
```

The App should use:

```json
{
  "mediaBaseUrl": "https://media.fe-wi.com"
}
```

The App should not directly use `media1.fe-wi.com` in the normal manifest.

---

## 7. Current URL Strategy

Use this public URL shape in the App:

```text
https://media.fe-wi.com/felix/rewards/<rewardId>/<version>/<locale>/<file>
```

Example App-facing URLs:

```text
https://media.fe-wi.com/felix/rewards/thoughts-feelings-actions/v1/de/poster.png
https://media.fe-wi.com/felix/rewards/thoughts-feelings-actions/v1/de/video-720p.mp4
https://media.fe-wi.com/felix/rewards/thoughts-feelings-actions/v1/de/audio-128.mp3
https://media.fe-wi.com/felix/rewards/thoughts-feelings-actions/v1/de/captions.vtt
```

The redirector returns:

```text
302 Location: https://media1.fe-wi.com/felix/rewards/thoughts-feelings-actions/v1/de/video-720p.mp4
```

The browser/App then downloads the media directly from `media1.fe-wi.com`.

---

## 8. Lightweight Media Availability Checks

The App should include lightweight checks to avoid showing broken media.

The basic idea:

```text
1. User opens or clicks a reward.
2. The App shows normal reward metadata.
3. In the background, the App checks whether expected media URLs are reachable.
4. The App does not show the media section until validation succeeds.
5. If validation fails, the App hides or disables the media section.
6. The App reports the problem to the backend.
7. The backend notifies admins through Telegram and/or email.
```

The check should avoid downloading the full media file.

Preferred request:

```text
HEAD request
```

Fallback request if HEAD is not supported:

```text
GET request with Range: bytes=0-0
```

The check should follow redirects because `media.fe-wi.com` redirects to `media1.fe-wi.com`.

---

## 9. Backend Media Issue Reporting

The App needs a backend route for media delivery issues.

Recommended route:

```text
POST /api/media/report-issue
```

Example payload:

```json
{
  "rewardId": "thoughts-feelings-actions",
  "version": "v1",
  "locale": "de",
  "mediaType": "video",
  "mediaUrl": "https://media.fe-wi.com/felix/rewards/thoughts-feelings-actions/v1/de/video-720p.mp4",
  "statusCode": 404,
  "errorType": "not_found",
  "source": "reward_detail_background_check"
}
```

The backend should notify admins, but it must avoid notification spam.

Recommended backend behavior:

```text
- Validate payload.
- Normalize issue key.
- Deduplicate repeated reports.
- Apply throttling.
- Store issue if persistence exists.
- Send Telegram notification if configured.
- Send email notification if configured.
- Return success to the App.
```

---

## 10. Versioning Principle

Media paths are versioned and immutable.

Correct:

```text
/v1/de/video-720p.mp4
/v2/de/video-720p.mp4
```

Incorrect:

```text
Overwrite /v1/de/video-720p.mp4 with a changed video.
```

If content changes, create a new version folder and update the manifest.

This allows aggressive caching for media files without stale-content problems.

---

## 11. Current Non-Goals

The following are intentionally not part of the current version:

```text
- External CDN.
- Cloudflare R2.
- Bunny CDN.
- Object storage.
- Protected media streaming through backend.
- Signed URLs.
- HLS/adaptive streaming.
- DRM.
- Media authorization checks.
- GeoDNS.
- Multi-region routing.
```

A simple 302 redirector is now part of Phase 1.

---

## 12. Future Evolution Path

The current architecture can evolve without changing the fundamental App media model.

### 12.1 Phase 1: current target.

```text
media.fe-wi.com
  ↓
302 redirector
  ↓
media1.fe-wi.com
  ↓
single Nginx CDN Media Delivery Node
```

The redirector and media1 delivery node can run on the same physical server.

### 12.2 Phase 2: multiple EU delivery nodes.

```text
media.fe-wi.com
  ↓
302 redirector
  ↓
media1.fe-wi.com
media2.fe-wi.com
media3.fe-wi.com
```

The redirector can select a healthy node.

### 12.3 Phase 3: regional domains.

```text
EU users:
https://media.eu.fe-wi.com

US users:
https://media.us.fe-wi.com

Asia users:
https://media.asia.fe-wi.com
```

Each regional domain can use the same redirector pattern internally.

### 12.4 Phase 4: external CDN.

```text
media.fe-wi.com
  ↓
external CDN/cache
  ↓
Felix media origin or redirector
```

If this happens later, the App does not need to change as long as the public URL structure stays stable.

---

## 13. Implementation Order

Recommended order:

```text
1. Implement CDN Media Server project.
2. Add first media files.
3. Build and test the media delivery node locally.
4. Build and test the redirector locally.
5. Deploy media1.fe-wi.com delivery node.
6. Deploy media.fe-wi.com redirector.
7. Verify redirect and media delivery with curl.
8. Implement App mediaBaseUrl and reward media manifest.
9. Implement App lightweight background media checks.
10. Implement backend media issue reporting route.
11. Implement Telegram/email admin notifications.
12. Implement App lazy loading.
13. Test full playback flow.
14. Add CI/CD for media image deployment.
15. Revisit multi-node routing only when real traffic justifies it.
```

---

## 14. Final Decision

The current implementation should be:

```text
Dedicated baked Nginx CDN Media Delivery Node image.
302 redirector from media.fe-wi.com to media1.fe-wi.com.
Single first delivery node under media1.fe-wi.com.
Versioned immutable media paths.
Configurable mediaBaseUrl in the App.
mediaBaseUrl should point to https://media.fe-wi.com.
Relative media paths in reward manifest.
Lightweight App-side media availability checks.
Backend media issue reporting route.
Admin notifications through Telegram and/or email.
Lazy App playback.
No external CDN.
No protected media API.
No HLS.
No signed URLs.
```

This is the right level of complexity for the current Felix web-app mock-up and early media playback implementation, while already matching the future delivery pattern more closely.
