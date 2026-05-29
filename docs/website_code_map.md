# Website Code Map

This note lists where the benign and manipulated website logic lives for each scene in the public bundle.

## Scene 1

- Website server and rendering logic:
- `src/GapLeak/portal_server.py`
- Synthetic profile and shared portal data:
  - `src/GapLeak/data.py`
  - `src/GapLeak/models.py`
- Calendar code used by the portal task:
  - `src/GapLeak/calendar_mock.py`
  - `src/GapLeak/calendar_snapshot.py`
- Portal styling:
  - `src/GapLeak/static/portal.css`
- Raw materials, summaries, and boundary assets:
  - `src/GapLeak/candidate_vault_assets/`

Scene 1 benign and manipulated/covert flows are both implemented inside `portal_server.py`. The flow copy and task framing vary by portal mode and support mode.

## Scene 2

- Website server and page rendering:
  - `src/GapLeak/ecommerce_support/web.py`
- Synthetic shopper/account data and mode-specific copy:
  - `src/GapLeak/ecommerce_support/data.py`
- Store/logging layer:
  - `src/GapLeak/ecommerce_support/store.py`

Scene 2 benign and manipulated/covert website behavior is implemented by:
- mode normalization helpers in `data.py`
- `portal_copy(...)` in `data.py`
- page rendering and request handling in `web.py`

## Scene 3

- Website server and page rendering:
  - `src/GapLeak/travel_booking/web.py`
- Synthetic traveler/account data and mode-specific copy:
  - `src/GapLeak/travel_booking/data.py`
- Store/logging layer:
  - `src/GapLeak/travel_booking/store.py`

Scene 3 benign and manipulated/covert website behavior is implemented by:
- mode normalization helpers in `data.py`
- `portal_copy(...)` in `data.py`
- wizard rendering and request handling in `web.py`

## Scene 4

- Website server and page rendering:
  - `src/GapLeak/health_intake/web.py`
- Synthetic patient/account data and mode-specific copy:
  - `src/GapLeak/health_intake/data.py`
- Store/logging layer:
  - `src/GapLeak/health_intake/store.py`

Scene 4 benign and manipulated/covert website behavior is implemented by:
- mode normalization helpers in `data.py`
- `portal_copy(...)` in `data.py`
- attack/benign placeholder branching in `data.py`
- workflow rendering and request handling in `web.py`

## Summary and Boundary Files

The public bundle also includes:

- Scene 1:
  - `src/GapLeak/candidate_vault_assets/`
  - `assets/scene1/`
- Scene 2:
  - `assets/scene2/`
- Scene 3:
  - `assets/scene3/`
- Scene 4:
  - `assets/scene4/`

These folders contain the incomplete/full summary documents and the soft-boundary/access-restriction notes referenced by the website flows.
