---
title: "feat: Browser notifications at pricing level milestones"
type: feat
date: 2026-02-13
---

# Browser Notifications at Pricing Level Milestones

Notify users in the browser when all cities in a pricing level (PL) finish validation during a test run. Uses in-page toast notifications when the tab is focused, and native Browser Notification API popups when the tab is backgrounded.

## Acceptance Criteria

- [x] When all selected cities in a pricing level complete (success or failure), a milestone event fires
- [x] Focused tab: an in-page toast shows (e.g., "PL1 Complete -- British Columbia: 12/12 cities validated")
- [x] Backgrounded tab: a native browser notification shows with the same info
- [x] Clicking the native notification focuses the validation tab
- [x] Notification permission is requested when the user clicks "Run Validation" (not on page load)
- [x] If permission is denied, toast notifications still work for all milestones
- [x] Failed locations count as "complete" for PL milestone tracking (toast shows failure count)
- [x] Milestones are persisted in job state so the polling fallback can deliver missed milestones after SSE disconnect
- [x] The final PL milestone is suppressed when it coincides with job completion (avoids redundant notification before results screen)
- [x] Multiple simultaneous milestones display as stacked toasts (max 3 visible, FIFO queue, auto-dismiss after 5 seconds)

## Context

**Existing infrastructure:**
- SSE streaming at `/stream/{job_id}` already pushes real-time progress to the browser (`src/web/app.py:459`)
- Toast notification component (HTML + JS + CSS) exists on the admin page (`src/web/templates/admin.html:156-192`) with CSS in `src/web/static/styles.css:694-734`
- All locations run in parallel via `asyncio.gather()` in `src/browser_automation.py:576`

**Key gap:** There is no per-location completion event. `_run_async()` awaits all locations via `asyncio.gather()` and returns only when everything is done. The progress callback (`_report_progress`) only sends flat string messages -- no structured events, no location-complete signal.

**Pricing levels:** PL1 (BC, 12 cities), PL2 (AB/SK, 10 cities), PL2-B (Fort McMurray/Peace River, 2 cities), PL3 (Yukon, 1 city), PL4 (Ontario, 7 cities). Users may select a subset.

## MVP

### 1. Backend: Track per-PL completion in job state

**`src/web/app.py`** -- Enhance `run_validation_task()`:

```python
# In run_validation_task(), after parsing selected cities, build PL tracking:

# Group selected cities by pricing level
pl_groups = {}
for city_str in selected_cities:
    pl_code = city_str.split(":")[0]
    pl_groups.setdefault(pl_code, []).append(city_str)

# Add to job state
await update_job(job_id,
    pl_progress={
        pl: {"total": len(cities), "completed": 0, "succeeded": 0, "failed": 0}
        for pl, cities in pl_groups.items()
    },
    milestones=[]
)
```

### 2. Backend: Wrap location tasks to report completion

**`src/web/app.py`** -- Wrap each location coroutine in `run_validation_task()`:

```python
# Instead of calling automation._run_async() as a black box,
# wrap each _validate_location call to detect completion:

async def location_with_tracking(coro, pl_code, city_name):
    """Wrap a location validation coroutine to track PL-level completion."""
    try:
        result = await coro
        success = not isinstance(result, Exception)
    except Exception:
        success = False
        result = None

    # Atomically update PL counter and check for milestone
    async with jobs_lock:
        job = jobs[job_id]
        pl = job["pl_progress"][pl_code]
        pl["completed"] += 1
        pl["succeeded" if success else "failed"] += 1

        # Check if this PL is now complete
        if pl["completed"] == pl["total"]:
            pl_name = PL_NAMES.get(pl_code, pl_code)  # e.g., "British Columbia"
            milestone = {
                "type": "pl_complete",
                "pl_code": pl_code,
                "pl_name": pl_name,
                "cities_succeeded": pl["succeeded"],
                "cities_failed": pl["failed"],
                "cities_total": pl["total"],
                "timestamp": datetime.now().isoformat(),
            }
            job["milestones"].append(milestone)

    return result
```

### 3. Backend: Emit milestone events via SSE

**`src/web/app.py`** -- Enhance the `/stream/{job_id}` SSE endpoint:

```python
# In event_generator(), after yielding the job state, also check for new milestones:

last_milestone_idx = 0

while True:
    async with jobs_lock:
        job = jobs[job_id].copy()
        milestones = job.get("milestones", [])

    # Send progress update (existing behavior)
    yield f"data: {json.dumps(job)}\n\n"

    # Send any new milestone events (named SSE events)
    for ms in milestones[last_milestone_idx:]:
        yield f"event: milestone\ndata: {json.dumps(ms)}\n\n"
    last_milestone_idx = len(milestones)

    if job["status"] in ("completed", "error"):
        break
    await asyncio.sleep(1)
```

### 4. Frontend: Port toast component and add stacking

**`src/web/templates/index.html`** -- Add toast container and queue logic:

```html
<!-- Toast Container (add before closing </body>) -->
<div id="toastContainer" style="position:fixed;bottom:24px;left:50%;transform:translateX(-50%);z-index:2000;display:flex;flex-direction:column-reverse;gap:8px;pointer-events:none;"></div>
```

```javascript
// Toast queue with stacking (max 3 visible)
const TOAST_MAX = 3;
const TOAST_DURATION = 5000;

function showMilestoneToast(milestone) {
    const container = document.getElementById('toastContainer');
    const toast = document.createElement('div');
    toast.className = 'toast toast-success';
    toast.style.pointerEvents = 'auto';

    const failText = milestone.cities_failed > 0
        ? ` (${milestone.cities_failed} failed)` : '';
    toast.innerHTML = `
        <span class="material-icons toast-icon">check_circle</span>
        <span>${milestone.pl_code} Complete &mdash; ${milestone.pl_name}: ${milestone.cities_succeeded}/${milestone.cities_total} cities${failText}</span>
    `;

    container.appendChild(toast);

    // Enforce max visible
    while (container.children.length > TOAST_MAX) {
        container.removeChild(container.firstChild);
    }

    setTimeout(() => toast.remove(), TOAST_DURATION);
}
```

### 5. Frontend: Browser Notification API + focus detection

**`src/web/templates/index.html`** -- Add notification logic:

```javascript
// Request permission when user clicks Run Validation (in the submit handler)
async function requestNotificationPermission() {
    if ('Notification' in window && Notification.permission === 'default') {
        await Notification.requestPermission();
    }
}

// Determine notification channel based on tab visibility
function notifyMilestone(milestone) {
    const isHidden = document.visibilityState === 'hidden';

    if (isHidden && 'Notification' in window && Notification.permission === 'granted') {
        const failText = milestone.cities_failed > 0
            ? ` (${milestone.cities_failed} failed)` : '';
        const n = new Notification(`${milestone.pl_code} Complete`, {
            body: `${milestone.pl_name} -- ${milestone.cities_succeeded}/${milestone.cities_total} cities validated${failText}`,
            tag: `panago-pl-${milestone.pl_code}`,
            icon: '/static/favicon.ico',
        });
        n.onclick = () => { window.focus(); n.close(); };
    } else {
        showMilestoneToast(milestone);
    }
}
```

### 6. Frontend: Wire up SSE milestone listener

**`src/web/templates/index.html`** -- In `startPolling()`:

```javascript
function startPolling(jobId) {
    eventSource = new EventSource('/stream/' + jobId);
    let seenMilestones = 0;

    // Existing progress handler
    eventSource.onmessage = function(event) {
        const data = JSON.parse(event.data);
        updateProgress(data);
        if (data.status === 'completed') {
            eventSource.close();
            showResults(data);
        } else if (data.status === 'error') {
            eventSource.close();
            showError(data.message);
        }
    };

    // NEW: milestone event handler
    eventSource.addEventListener('milestone', function(event) {
        const milestone = JSON.parse(event.data);
        notifyMilestone(milestone);
    });

    eventSource.onerror = function() {
        eventSource.close();
        pollStatus(jobId);  // Fallback -- milestones available via job state
    };
}
```

### 7. Frontend: Polling fallback for missed milestones

**`src/web/templates/index.html`** -- In `pollStatus()`:

```javascript
// In the polling fallback, detect new milestones from job state:
let seenMilestonesPoll = 0;

function pollStatus(jobId) {
    const interval = setInterval(async () => {
        const resp = await fetch('/status/' + jobId);
        const data = await resp.json();
        updateProgress(data);

        // Deliver any milestones missed during SSE disconnect
        const milestones = data.milestones || [];
        for (let i = seenMilestonesPoll; i < milestones.length; i++) {
            notifyMilestone(milestones[i]);
        }
        seenMilestonesPoll = milestones.length;

        if (data.status === 'completed') {
            clearInterval(interval);
            showResults(data);
        } else if (data.status === 'error') {
            clearInterval(interval);
            showError(data.message);
        }
    }, 2000);
}
```

### Files to modify

| File | Change |
|------|--------|
| `src/web/app.py` | Add `pl_progress` and `milestones` to job state; wrap location tasks for completion tracking; emit named SSE milestone events; add `PL_NAMES` mapping |
| `src/web/templates/index.html` | Add toast container HTML; add `showMilestoneToast()`, `notifyMilestone()`, `requestNotificationPermission()`; add SSE milestone listener; enhance polling fallback |
| `src/browser_automation.py` | Refactor `_run_async()` to accept a per-location completion callback, or expose individual location tasks so `app.py` can wrap them |
| `config/pricing_levels.yaml` | No changes needed (PL names already defined here) |
| `src/web/static/styles.css` | Minor CSS addition for stacked toast positioning (existing `.toast` styles cover single toast) |

## References

- Existing SSE endpoint: `src/web/app.py:459-489`
- Toast component to port: `src/web/templates/admin.html:156-192`
- Toast CSS: `src/web/static/styles.css:694-734`
- Location processing: `src/browser_automation.py:539-592` (`_run_async`)
- Per-location validation: `src/browser_automation.py:624-643` (`_validate_location`)
- Pricing levels config: `config/pricing_levels.yaml`
- Solution doc: `docs/solutions/feature-patterns/cli-to-web-ui-wrapper.md`
