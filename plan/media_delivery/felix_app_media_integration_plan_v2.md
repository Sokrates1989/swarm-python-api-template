# Felix App Media Integration Plan

## 1. Purpose

This document describes the App-side implementation for Felix reward media playback.

The App should not store audio or video binaries. The App should only store or receive metadata and media paths.

The current goal is:

```text
Use public media URLs from the CDN Media Server.
Use media.fe-wi.com as stable App-facing media base URL.
Let the server-side redirector redirect to the concrete delivery node.
Construct final media URLs from mediaBaseUrl + relative media path.
Run lightweight media availability checks before showing media controls.
Report broken or unavailable media to the backend.
Load audio/video only when the user explicitly starts playback.
```

This document intentionally uses the term `App` because the current implementation is a web-app mock-up, and the media architecture should remain independent of a specific app platform.

---

## 2. Related Documents

The server-side media hosting implementation is defined here:

- [CDN Media Server Plan](./felix_cdn_media_server_plan_v2.md)

The overall purpose and decision summary are defined here:

- [Felix Media Delivery Plan Overview](./felix_media_delivery_overview_v2.md)

---

## 3. App Responsibilities

The App is responsible for:

```text
- Showing reward metadata.
- Showing whether a reward is available or unlocked.
- Building final media URLs.
- Running lightweight media availability checks.
- Showing media controls only after media availability is confirmed.
- Reporting broken or unavailable media to the backend.
- Starting playback only after user action.
- Showing loading states.
- Showing graceful error states.
- Releasing media resources when the user leaves the reward detail view.
```

The App is not responsible for:

```text
- Hosting binary media files.
- Streaming media through the backend.
- Enforcing direct media URL protection.
- Performing CDN or server-side routing.
- Sending admin notifications directly.
```

Admin notifications are a backend responsibility.

---

## 4. App Configuration Strategy

The App should use a configurable media base URL.

Current default:

```json
{
  "mediaBaseUrl": "https://media.fe-wi.com"
}
```

Important:

```text
The App should use media.fe-wi.com, not media1.fe-wi.com.
```

Reason:

```text
media.fe-wi.com is the stable redirector entrypoint.
media1.fe-wi.com is only the first concrete delivery node.
```

The App should not scatter full media URLs throughout the codebase.

Instead, store one base URL and combine it with relative media paths.

Example:

```text
finalUrl = mediaBaseUrl + mediaPath
```

This keeps the App flexible.

If the media infrastructure changes later, the App only needs a configuration change.

---

## 5. Future Region Configuration

For now, the App can use one media entrypoint:

```json
{
  "mediaBaseUrl": "https://media.fe-wi.com"
}
```

Later, the config may become:

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
The backend or app config returns the preferred mediaBaseUrl.
The App uses that mediaBaseUrl for all reward media.
```

Avoid storing personal user identifiers in media URLs.

---

## 6. Media URL Structure

The final App-facing media URL should follow this structure:

```text
https://media.fe-wi.com/felix/rewards/<rewardId>/<version>/<locale>/<file>
```

Example:

```text
https://media.fe-wi.com/felix/rewards/thoughts-feelings-actions/v1/de/poster.png
https://media.fe-wi.com/felix/rewards/thoughts-feelings-actions/v1/de/video-720p.mp4
https://media.fe-wi.com/felix/rewards/thoughts-feelings-actions/v1/de/audio-128.mp3
https://media.fe-wi.com/felix/rewards/thoughts-feelings-actions/v1/de/captions.vtt
```

The redirector will redirect to the actual node:

```text
https://media1.fe-wi.com/felix/rewards/thoughts-feelings-actions/v1/de/video-720p.mp4
```

The App should normally not construct `media1.fe-wi.com` URLs directly.

In the App manifest, prefer relative paths:

```text
/felix/rewards/thoughts-feelings-actions/v1/de/video-720p.mp4
```

Then build:

```text
https://media.fe-wi.com + /felix/rewards/thoughts-feelings-actions/v1/de/video-720p.mp4
```

---

## 7. Reward Media Manifest Shape

Recommended manifest shape:

```json
{
  "mediaBaseUrl": "https://media.fe-wi.com",
  "rewards": {
    "thoughts-feelings-actions": {
      "rewardId": "thoughts-feelings-actions",
      "version": "v1",
      "durationSeconds": 44,
      "mediaType": "video",
      "locales": {
        "de": {
          "posterPath": "/felix/rewards/thoughts-feelings-actions/v1/de/poster.png",
          "videoPath": "/felix/rewards/thoughts-feelings-actions/v1/de/video-720p.mp4",
          "audioPath": "/felix/rewards/thoughts-feelings-actions/v1/de/audio-128.mp3",
          "captionsPath": "/felix/rewards/thoughts-feelings-actions/v1/de/captions.vtt"
        },
        "en": {
          "posterPath": "/felix/rewards/thoughts-feelings-actions/v1/en/poster.png",
          "videoPath": "/felix/rewards/thoughts-feelings-actions/v1/en/video-720p.mp4",
          "audioPath": "/felix/rewards/thoughts-feelings-actions/v1/en/audio-128.mp3",
          "captionsPath": "/felix/rewards/thoughts-feelings-actions/v1/en/captions.vtt"
        }
      }
    }
  }
}
```

If the App already has a reward content model, add media fields without mixing binary files into the reward content files.

---

## 8. URL Construction Helper

Create a small helper function.

Example TypeScript-style pseudocode:

```ts
function buildMediaUrl(mediaBaseUrl: string, mediaPath: string): string {
  const normalizedBaseUrl = mediaBaseUrl.replace(/\/$/, "");
  const normalizedPath = mediaPath.startsWith("/") ? mediaPath : `/${mediaPath}`;

  return `${normalizedBaseUrl}${normalizedPath}`;
}
```

Example usage:

```ts
const videoUrl = buildMediaUrl(
  appConfig.mediaBaseUrl,
  reward.locales[currentLocale].videoPath
);
```

This prevents duplicated slashes and keeps URL construction consistent.

---

## 9. Locale Handling

The App should select the media locale based on the current App language.

Recommended fallback:

```text
1. Use current App locale if available.
2. Fallback to English.
3. Fallback to German only if English is unavailable.
4. Show graceful error if no media locale exists.
```

Example:

```ts
function resolveRewardMediaLocale(
  availableLocales: string[],
  currentLocale: string
): string | null {
  if (availableLocales.includes(currentLocale)) {
    return currentLocale;
  }

  if (availableLocales.includes("en")) {
    return "en";
  }

  if (availableLocales.includes("de")) {
    return "de";
  }

  return null;
}
```

---

## 10. Lightweight Media Availability Check

The App should verify media availability before showing media controls.

This avoids showing a broken player or broken media link.

### 10.1 When to run the check.

Run the check when the user opens or clicks a reward.

Recommended behavior:

```text
1. User opens reward detail.
2. App renders text metadata immediately.
3. App starts lightweight media availability check in the background.
4. App shows a small loading/skeleton state for the media section if needed.
5. If media is available, App shows poster and play controls.
6. If media is unavailable, App hides the media section or shows a neutral fallback.
7. App reports the issue to the backend.
```

Do not block the entire reward detail page while checking media.

### 10.2 What to check.

At minimum, check the primary file needed for the current reward media type.

For video rewards:

```text
- videoPath
- posterPath if the poster is required
- captionsPath if captions are expected
```

For audio rewards:

```text
- audioPath
- posterPath if the audio reward uses a visual cover/poster
```

Captions should not block media display if they are optional.

### 10.3 Preferred check method.

Use:

```http
HEAD <media-url>
```

Expected success:

```text
HTTP 200
```

Redirects are expected:

```text
media.fe-wi.com → media1.fe-wi.com
```

The check must follow redirects.

### 10.4 Fallback check method.

Some servers or environments may not handle `HEAD` exactly like `GET`.

Fallback:

```http
GET <media-url>
Range: bytes=0-0
```

Expected success:

```text
HTTP 206 Partial Content
```

or:

```text
HTTP 200
```

The purpose is to avoid downloading the full media file.

### 10.5 Timeout.

Use a short timeout.

Recommended:

```text
3 to 5 seconds.
```

If the check times out, treat it as unavailable for the current UI session and report the issue.

### 10.6 Result model.

Example:

```ts
type MediaAvailabilityStatus =
  | "unknown"
  | "checking"
  | "available"
  | "unavailable";
```

Example per media item:

```ts
type MediaAvailabilityResult = {
  mediaType: "poster" | "video" | "audio" | "captions";
  url: string;
  available: boolean;
  statusCode?: number;
  errorType?: string;
  checkedAt: string;
};
```

---

## 11. Media Section UI Behavior

The media section should be conditional.

### Initial state.

```text
Reward text and metadata are visible.
Media section is not shown yet or shows a subtle loading placeholder.
```

### Check succeeds.

```text
Show poster.
Show play button.
Enable video/audio controls.
```

### Check fails.

```text
Do not show broken player.
Do not show broken direct media link.
Hide the media section or show a calm fallback message.
Report issue to backend.
```

Recommended fallback message only if needed:

```text
Dieses Medium ist gerade nicht verfügbar.
```

For a reward where media is optional, simply hiding the section is acceptable.

---

## 12. Backend Media Issue Reporting Route

The App needs to call a backend route when a media issue is detected.

Recommended route:

```text
POST /api/media/report-issue
```

Alternative if backend route naming conventions differ:

```text
POST /api/admin/media-issues/report
```

Recommended request payload:

```json
{
  "rewardId": "thoughts-feelings-actions",
  "version": "v1",
  "locale": "de",
  "mediaType": "video",
  "mediaUrl": "https://media.fe-wi.com/felix/rewards/thoughts-feelings-actions/v1/de/video-720p.mp4",
  "statusCode": 404,
  "errorType": "not_found",
  "source": "reward_detail_background_check",
  "userAgent": "optional",
  "appVersion": "optional",
  "checkedAt": "2026-06-08T12:00:00Z"
}
```

### Do not send sensitive user data.

Do not include:

```text
- user email
- user name
- user ID unless explicitly needed
- access tokens
- authentication headers
- personal notes
```

A media availability issue is normally not user-specific.

### Expected backend response.

```json
{
  "ok": true
}
```

The App should not fail the reward page if the issue reporting request fails.

---

## 13. Backend Admin Notification Requirements

The backend should notify admins when media issues are reported.

The App only reports the issue. The backend sends notifications.

Admin notification channels:

```text
- Telegram message.
- Email message.
```

Backend requirements:

```text
- Validate incoming issue reports.
- Deduplicate repeated issue reports.
- Throttle notifications.
- Send Telegram message if configured.
- Send email message if configured.
- Return success to the App even if notification is queued.
```

Recommended deduplication key:

```text
rewardId + version + locale + mediaType + statusCode + errorType
```

Recommended throttling:

```text
Do not notify admins more than once per issue key within 30 to 60 minutes.
```

Recommended admin message:

```text
Felix media issue detected.

Reward: thoughts-feelings-actions
Version: v1
Locale: de
Media type: video
Status: 404
Error: not_found
URL: https://media.fe-wi.com/felix/rewards/thoughts-feelings-actions/v1/de/video-720p.mp4
Source: reward_detail_background_check
```

---

## 14. Lazy Loading Strategy

The App should not load media until the user explicitly interacts.

### Reward list.

Do:

```text
- show title
- show description
- show reward state
- show duration
```

Do not:

```text
- create video player instances
- create audio player instances
- preload videos
- autoplay videos
- autoplay audio
```

Poster images in the list are optional. If shown, use normal image lazy loading.

### Reward detail.

Do:

```text
- show reward metadata immediately
- run media availability check in background
- show poster and play button only after availability check succeeds
```

Do not:

```text
- autoplay immediately
- initialize video/audio before user action
```

### On play.

Do:

```text
1. Resolve locale.
2. Build media URL.
3. Initialize player.
4. Show loading state.
5. Start playback.
6. Show error state if playback fails.
7. Report playback failure to backend if it appears to be a delivery problem.
```

---

## 15. Playback State Model

Use a clear playback state model.

Example:

```ts
type MediaPlaybackState =
  | "idle"
  | "checking"
  | "available"
  | "unavailable"
  | "loading"
  | "playing"
  | "paused"
  | "ended"
  | "error";
```

Recommended UI behavior:

```text
idle:
  media status unknown

checking:
  show subtle placeholder or no media section

available:
  show poster and play button

unavailable:
  hide media section or show calm fallback

loading:
  show poster and loading indicator

playing:
  show player controls

paused:
  show resume button/player controls

ended:
  show replay button

error:
  show message and retry button
```

---

## 16. Poster Handling

Poster images may be loaded after availability check or as part of the check.

Allowed:

```text
- Load poster when reward detail opens after poster check succeeds.
- Load poster in reward list if visible and useful.
```

Avoid:

```text
- Loading all posters for a large list at once.
- Loading video just to generate a preview frame.
```

Poster URL example:

```text
https://media.fe-wi.com/felix/rewards/thoughts-feelings-actions/v1/de/poster.png
```

---

## 17. Video Handling

Video file recommendation:

```text
video-720p.mp4
```

The App should:

```text
- check video availability before showing the video player
- use the video URL only after the user presses play
- rely on browser/app media controls where appropriate
- support pause/resume
- show a loading state while the video initializes
- show a graceful error if the URL fails
- report delivery-related failures to backend
```

Do not preload video in the reward list.

---

## 18. Audio Handling

Audio file recommendation:

```text
audio-128.mp3
```

The App should:

```text
- check audio availability before showing audio controls
- use the audio URL only after the user presses play
- provide pause/resume
- show progress if the player supports it
- handle loading and error states
- report delivery-related failures to backend
```

Audio is useful if the user wants a lightweight spoken reward without video playback.

---

## 19. Captions Handling

Captions should use WebVTT.

Recommended file name:

```text
captions.vtt
```

The App should use the captions path if video playback supports captions.

Do not rely on `.srt` files for web-style playback.

If source captions are `.srt`, convert them to `.vtt` before deployment.

Captions availability should usually not block showing the video unless captions are required for the specific reward.

---

## 20. Reward Unlock Behavior

The App/backend controls reward availability.

The media server does not enforce unlock status.

This means:

```text
The App decides when to show the media play button.
The CDN Media Server simply serves public files.
```

This is acceptable because the current reward videos are informational content.

Important:

```text
Do not put user IDs or unlock tokens into media URLs.
```

---

## 21. App Error Handling

The App should handle:

```text
- missing media URL
- unsupported locale
- failed HEAD check
- failed Range check
- redirect failure
- network error
- 404 media file
- playback initialization failure
- user offline state
```

Recommended user-facing behavior:

```text
Show a calm message only if needed:
"Dieses Medium ist gerade nicht verfügbar."

Provide:
- retry button if useful
- close/back option
```

Keep errors non-blocking. The reward screen should remain usable even if media playback fails.

---

## 22. App Testing Checklist

### Configuration.

```text
- mediaBaseUrl is loaded correctly.
- mediaBaseUrl uses https://media.fe-wi.com.
- mediaBaseUrl has no trailing slash issues.
- relative paths are combined correctly.
```

### Redirects.

```text
- App-facing URL points to media.fe-wi.com.
- Availability check follows redirect to media1.fe-wi.com.
- Final media playback works after redirect.
```

### Locale.

```text
- German media loads for German locale.
- English media loads for English locale.
- fallback locale works.
- missing locale shows graceful error.
```

### Lightweight availability check.

```text
- HEAD request succeeds for available media.
- fallback Range request works if needed.
- missing media is detected.
- media controls are hidden if check fails.
- backend issue report is sent on failure.
- reward text remains visible even if media fails.
```

### Lazy loading.

```text
- reward list does not initialize video.
- reward list does not initialize audio.
- reward detail does not autoplay.
- media starts loading only after play.
```

### Playback.

```text
- poster displays after validation.
- video plays.
- audio plays.
- captions are available if supported.
- pause/resume works.
- leaving the screen stops/disposes playback.
```

### Errors.

```text
- 404 media file shows graceful handling.
- invalid URL shows graceful handling.
- network failure shows graceful handling.
- issue reporting failure does not break the reward page.
```

---

## 23. App Implementation Prompt For Codex

```text
Implement Felix App-side reward media integration using public CDN Media Server URLs.

Use the generic term App in code comments and documentation where possible.

Current media base URL:
https://media.fe-wi.com

Do not use media1.fe-wi.com directly in the normal App manifest.
media1.fe-wi.com is the first concrete delivery node behind the redirector.

Do not bundle media files into the App.
Do not implement protected media API playback.
Do not implement signed URLs.
Do not implement HLS.
Do not implement external CDN logic.

Add or adapt a reward media manifest model with:
- rewardId
- version
- durationSeconds
- mediaType
- locale-specific posterPath
- locale-specific videoPath
- locale-specific audioPath
- locale-specific captionsPath

Use a configurable mediaBaseUrl.
Build final media URLs as:
mediaBaseUrl + relative media path

Implement lightweight media availability checks:
- run when the user opens/clicks a reward
- use HEAD request first
- follow redirects
- fallback to GET with Range: bytes=0-0 if needed
- use a short timeout
- do not download full media content
- do not show media controls until the relevant media check succeeds
- hide or gracefully fallback if media is unavailable

Implement backend issue reporting:
- call POST /api/media/report-issue when media availability check fails
- include rewardId, version, locale, mediaType, mediaUrl, statusCode if available, errorType and source
- do not include sensitive user data
- do not break the reward page if reporting fails

In reward lists:
- do not initialize video players
- do not initialize audio players
- optionally show poster image only if needed

In reward detail:
- show reward text immediately
- run media check asynchronously in the background
- show poster, duration and play button only after media is available
- initialize media only after the user presses play
- show loading state
- show graceful error state
- dispose media resources when leaving the screen

Use WebVTT captions via captions.vtt if supported by the current player implementation.

Keep the App implementation independent of the current server implementation.
The mediaBaseUrl may later point to another region or a more advanced redirector.
```

---

## 24. Backend Implementation Prompt For Codex

```text
Implement a backend media issue reporting route for Felix.

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
Use the normal backend validation and rate limiting patterns.

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

The route must not stream media files.
The route must not implement protected media delivery.
The route only reports delivery issues to admins.
```

---

## 25. Final App Decision

The App implementation should be:

```text
Configurable mediaBaseUrl.
mediaBaseUrl points to https://media.fe-wi.com.
Relative media paths.
Versioned reward media manifest.
Lightweight availability checks before showing media controls.
Backend issue reporting for unavailable media.
Lazy loading.
No binary media bundled into the App.
No protected media API playback.
No App-side regional routing complexity yet.
```
