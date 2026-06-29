"""
One-off script to bootstrap the full Confluence structure.

Run with:
  cd /Users/deji/Dev/confluence-publisher
  export $(grep -v '^#' .env | grep '=' | xargs)
  venv/bin/python scripts/setup_confluence.py
"""

from __future__ import annotations

import base64
import os
import textwrap

import requests

BASE_URL = os.environ["CONFLUENCE_BASE_URL"].rstrip("/")
EMAIL = os.environ["CONFLUENCE_EMAIL"]
TOKEN = os.environ["CONFLUENCE_API_TOKEN"]

session = requests.Session()
session.headers["Authorization"] = "Basic " + base64.b64encode(f"{EMAIL}:{TOKEN}".encode()).decode()
session.headers["Content-Type"] = "application/json"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def v2(path: str) -> str:
    return f"{BASE_URL}/wiki/api/v2/{path.lstrip('/')}"


def v1(path: str) -> str:
    return f"{BASE_URL}/wiki/rest/api/{path.lstrip('/')}"


def get(url: str, **params) -> dict:
    r = session.get(url, params=params, timeout=30)
    r.raise_for_status()
    return r.json()


def post(url: str, payload: dict) -> dict:
    r = session.post(url, json=payload, timeout=30)
    if not r.ok:
        print(f"POST {url} -> {r.status_code}: {r.text[:400]}")
        r.raise_for_status()
    return r.json()


def delete(url: str) -> None:
    r = session.delete(url, timeout=30)
    if r.status_code not in (200, 204):
        print(f"DELETE {url} -> {r.status_code}: {r.text[:200]}")
    else:
        print(f"  deleted {url}")


def create_page(space_id: str, title: str, parent_id: str | None, body: str = "<p></p>") -> str:
    payload: dict = {
        "spaceId": space_id,
        "status": "current",
        "title": title,
        "body": {"representation": "storage", "value": body},
    }
    if parent_id:
        payload["parentId"] = parent_id
    data = post(v2("pages"), payload)
    page_id = data["id"]
    print(f"  created '{title}' -> {page_id}")
    return page_id


# ---------------------------------------------------------------------------
# Step 1: Clean up Bazzoniare template pages
# ---------------------------------------------------------------------------
BAZZONIARE_SPACE_ID = "65851"
BAZZONIARE_ROOT = "66015"
HELLO_WORLD_PAGE_ID = "327687"

TEMPLATE_PAGES = ["66029", "66042"]  # How-to guide, Troubleshooting article

print("\n=== Step 1: Clean up Bazzoniare template pages ===")
for pid in TEMPLATE_PAGES:
    r = session.get(v2(f"pages/{pid}"), timeout=30)
    if r.status_code == 404:
        print(f"  {pid} already gone, skipping")
    else:
        delete(v2(f"pages/{pid}"))


# ---------------------------------------------------------------------------
# Step 2: Create SearchAudit space (v1 API)
# ---------------------------------------------------------------------------
print("\n=== Step 2: Create SearchAudit space ===")

existing_spaces = get(v2("spaces"), limit=50)["results"]
sa_space = next((s for s in existing_spaces if s["key"] == "SA"), None)

if sa_space:
    SA_SPACE_ID = sa_space["id"]
    SA_ROOT_ID = sa_space["homepageId"]
    print(f"  SearchAudit space already exists: {SA_SPACE_ID}, root: {SA_ROOT_ID}")
else:
    post(
        v1("space"),
        {
            "key": "SA",
            "name": "SearchAudit",
            "description": {
                "plain": {
                    "value": "SearchAudit ETL pipeline — architecture, ADRs, and implementation notes.",
                    "representation": "plain",
                },
            },
        },
    )
    # Re-fetch from v2 list (v1 create response structure differs)
    spaces = get(v2("spaces"), limit=50)["results"]
    sa_space = next(s for s in spaces if s["key"] == "SA")
    SA_SPACE_ID = sa_space["id"]
    SA_ROOT_ID = sa_space["homepageId"]
    print(f"  SearchAudit space created: {SA_SPACE_ID}, root: {SA_ROOT_ID}")


# ---------------------------------------------------------------------------
# Step 3: Bazzoniare — confluence-publisher section
# ---------------------------------------------------------------------------
print("\n=== Step 3: Bazzoniare — confluence-publisher section ===")

cp_root = create_page(
    BAZZONIARE_SPACE_ID,
    "confluence-publisher",
    BAZZONIARE_ROOT,
    body=textwrap.dedent("""\
        <p>Documentation for the <strong>confluence-publisher</strong> tool — a one-way
        GitHub Markdown to Confluence publishing pipeline.</p>
        <p>These pages are published automatically from
        <code>github.com/donolu/confluence-publisher</code> via GitHub Actions.
        Do not edit directly in Confluence.</p>
    """),
)

CP_DOC_PAGES = [
    ("docs/BRD.md", "Business Requirements"),
    ("docs/TRD.md", "Technical Requirements"),
    ("docs/ARCHITECTURE.md", "Architecture"),
    ("docs/DELIVERY_PLAN.md", "Delivery Plan"),
    ("docs/DECISIONS.md", "Decisions & Open Questions"),
    ("docs/MANIFEST_SPEC.md", "Manifest Specification"),
]

cp_page_ids: dict[str, dict] = {}
for rel_path, title in CP_DOC_PAGES:
    pid = create_page(BAZZONIARE_SPACE_ID, title, cp_root)
    cp_page_ids[rel_path] = {"page_id": pid, "title": title}

# Move the existing Hello World test page under confluence-publisher
print(f"\n  moving Hello World ({HELLO_WORLD_PAGE_ID}) under confluence-publisher...")
r = session.get(v2(f"pages/{HELLO_WORLD_PAGE_ID}"), timeout=30)
r.raise_for_status()
hw = r.json()
r2 = session.put(
    v2(f"pages/{HELLO_WORLD_PAGE_ID}"),
    json={
        "id": HELLO_WORLD_PAGE_ID,
        "status": "current",
        "title": hw["title"],
        "parentId": cp_root,
        "version": {
            "number": hw["version"]["number"] + 1,
            "message": "moved to confluence-publisher section",
        },
        "body": {"representation": "storage", "value": "<p></p>"},
    },
    timeout=30,
)
if r2.ok:
    print(f"  moved Hello World -> parent={cp_root}")
else:
    print(f"  move failed ({r2.status_code}), keeping in place")


# ---------------------------------------------------------------------------
# Step 4: SearchAudit — page hierarchy
# ---------------------------------------------------------------------------
print("\n=== Step 4: SearchAudit — page hierarchy ===")

sa_arch = create_page(
    SA_SPACE_ID,
    "Architecture",
    SA_ROOT_ID,
    body="<p>Architecture documentation and design decisions for the SearchAudit ETL pipeline.</p>",
)
sa_adrs = create_page(
    SA_SPACE_ID,
    "Architecture Decision Records",
    SA_ROOT_ID,
    body="<p>ADRs capture significant decisions made during SearchAudit development.</p>",
)
sa_impl = create_page(
    SA_SPACE_ID,
    "Implementation Notes",
    SA_ROOT_ID,
    body="<p>Technical implementation notes, fix summaries, and how-to guides.</p>",
)
sa_analysis = create_page(
    SA_SPACE_ID,
    "Analysis & Research",
    SA_ROOT_ID,
    body="<p>Deep-dive analyses, comparisons, and research notes.</p>",
)

SA_DOC_PAGES: list[tuple[str, str, str]] = [
    # (rel_path_from_SearchAudit_root, title, parent_id)
    # Architecture
    ("docs/notion-import/07-Modern-Architecture-Documentation.md", "Modern Architecture", sa_arch),
    ("docs/notion-import/06-Implementation-Roadmap.md", "Implementation Roadmap", sa_arch),
    # ADRs
    (
        "docs/adr/ADR-004-config-driven-edge-case-handling.md",
        "ADR-004: Config-Driven Edge Case Handling",
        sa_adrs,
    ),
    (
        "docs/adr/ADR-004-moving-rate-calculations-review.md",
        "ADR-004: Moving Rate Calculations Review",
        sa_adrs,
    ),
    ("docs/adr/ADR-cross-session-conversions.md", "ADR: Cross-Session Conversions", sa_adrs),
    ("docs/adr/ADR-schema-validation-async.md", "ADR: Schema Validation (Async)", sa_adrs),
    ("docs/adr/ADR-schema-validation-options.md", "ADR: Schema Validation Options", sa_adrs),
    (
        "docs/adr/CONFIG_AUDIT_AND_HYBRID_IMPLEMENTATION.md",
        "Config Audit & Hybrid Implementation",
        sa_adrs,
    ),
    ("docs/adr/HYBRID_CONFIG_ARCHITECTURE_ALIGNED.md", "Hybrid Config Architecture", sa_adrs),
    (
        "docs/adr/PRE_PROCESSOR_ORPHANED_METHODS_ANALYSIS.md",
        "Pre-Processor: Orphaned Methods",
        sa_adrs,
    ),
    ("docs/adr/PRE_PROCESSOR_UNLOAD_ANALYSIS.md", "Pre-Processor: Unload Analysis", sa_adrs),
    ("docs/SEMANTIC_DESCRIPTIVE_STAMPING.md", "Semantic Descriptive Stamping", sa_adrs),
    ("docs/SEMANTIC_EVENTS_INDEX.md", "Semantic Events Index", sa_adrs),
    # Implementation
    ("docs/CENTRALIZED_EVENT_CONFIG_LOADING.md", "Centralised Event Config Loading", sa_impl),
    ("docs/CHECKPOINT_SPLIT_ISSUE.md", "Checkpoint Split Issue", sa_impl),
    ("docs/REFACTOR_CENTRALIZED_OPERATORS.md", "Refactor: Centralised Operators", sa_impl),
    (
        "docs/SESSION_ID_DUAL_FORMAT_IMPLEMENTATION.md",
        "Session ID: Dual Format Implementation",
        sa_impl,
    ),
    (
        "docs/SESSION_ID_FILTERING_IMPLEMENTATION.md",
        "Session ID: Filtering Implementation",
        sa_impl,
    ),
    (
        "docs/TODO_RESOLUTION_DYNAMIC_SEARCH_START.md",
        "TODO: Dynamic Search Start Resolution",
        sa_impl,
    ),
    ("docs/PRESERVE_ALL_INFO_IMPLEMENTATION.md", "Preserve All Info Implementation", sa_impl),
    ("docs/REMOVAL_CONVERSION_PRODUCT_FIELD.md", "Removal: Conversion Product Field", sa_impl),
    # Analysis
    ("docs/CONTENT_CONVERSION_ID_COMPARISON.md", "Content & Conversion ID Comparison", sa_analysis),
    ("docs/IN_FUNNEL_CLEAN_LOGIC_ANALYSIS.md", "In-Funnel Clean Logic Analysis", sa_analysis),
    ("docs/KATE_PR_ANALYSIS_FROM_DATA.md", "Kate: PR Analysis from Data", sa_analysis),
    (
        "docs/KATE_SOURCE_PRODUCT_CLARIFICATIONS.md",
        "Kate: Source Product Clarifications",
        sa_analysis,
    ),
    ("docs/search_events_analysis_2025_01_20.md", "Search Events Analysis (Jan 2025)", sa_analysis),
    ("docs/FIX_EXTENDED_SESSION_ID_MISSING.md", "Fix: Extended Session ID Missing", sa_analysis),
    ("docs/FIX_SESSION_DATE_NULL_ISSUE.md", "Fix: Session Date Null Issue", sa_analysis),
    ("docs/MODIFIED_FILES_LIST.md", "Modified Files Reference", sa_analysis),
]

sa_page_ids: dict[str, dict] = {}
for rel_path, title, parent_id in SA_DOC_PAGES:
    pid = create_page(SA_SPACE_ID, title, parent_id)
    sa_page_ids[rel_path] = {"page_id": pid, "title": title}


# ---------------------------------------------------------------------------
# Step 5: Print manifests
# ---------------------------------------------------------------------------
print("\n\n=== confluence-publisher manifest additions ===")
print("(add under pages: in confluence-manifest.yaml)")
for rel, info in cp_page_ids.items():
    print(f"  {rel}:")
    print(f"    page_id: '{info['page_id']}'")
    print(f"    title: {info['title']}")

print(
    "\n\n=== SearchAudit manifest (save as /Users/deji/Dev/SearchAudit/confluence-manifest.yaml) ==="
)
print("version: 1")
print("defaults:")
print("  space_id: SA")
print("  parent_id: ''")
print("pages:")
for rel, info in sa_page_ids.items():
    print(f"  {rel}:")
    print(f"    page_id: '{info['page_id']}'")
    print(f"    title: {info['title']}")

print("\n\nDone.")
