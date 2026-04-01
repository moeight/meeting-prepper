# Meeting Prepper v1.1
"""
Meeting Prepper — Backend API
Vercel Python serverless function (also runs locally via Flask).

Pipeline:
  1. Parallel data gathering  → Exa (web search) + Apify (scraping/Instagram)
  2. Single Claude call       → Structured brief JSON using bias framework
  3. Return JSON              → Frontend renders the cheat sheet
"""

from flask import Flask, request, jsonify
from flask_cors import CORS
import anthropic
import httpx
import asyncio
import json
import os
import re

app = Flask(__name__)
CORS(app)

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
APIFY_TOKEN       = os.environ.get("APIFY_TOKEN", "")
EXA_API_KEY       = os.environ.get("EXA_API_KEY", "")


# ── Data Gathering ─────────────────────────────────────────────────────────────

async def exa_search(client: httpx.AsyncClient, query: str, num_results: int = 6) -> list:
    """Semantic web search via Exa.ai — returns list of {title, url, text}."""
    if not EXA_API_KEY:
        return []
    try:
        resp = await client.post(
            "https://api.exa.ai/search",
            headers={"x-api-key": EXA_API_KEY, "Content-Type": "application/json"},
            json={
                "query": query,
                "num_results": num_results,
                "type": "auto",
                "contents": {"text": {"max_characters": 1500}},
            },
            timeout=12.0,
        )
        return resp.json().get("results", [])
    except Exception:
        return []


async def apify_scrape_url(client: httpx.AsyncClient, url: str) -> str:
    """Scrape any URL using Apify RAG Web Browser — returns plain text."""
    if not APIFY_TOKEN:
        return ""
    try:
        resp = await client.post(
            f"https://api.apify.com/v2/acts/apify~rag-web-browser/run-sync-get-dataset-items?token={APIFY_TOKEN}",
            json={"startUrls": [{"url": url}], "maxCrawlDepth": 0, "maxResults": 1},
            timeout=22.0,
        )
        items = resp.json()
        if items and isinstance(items, list):
            return items[0].get("text", "")[:3000]
        return ""
    except Exception:
        return ""


async def apify_instagram(client: httpx.AsyncClient, instagram_url: str) -> dict:
    """Scrape Instagram profile via Apify — returns profile + recent posts."""
    if not APIFY_TOKEN:
        return {}
    username = (
        instagram_url
        .replace("https://www.instagram.com/", "")
        .replace("https://instagram.com/", "")
        .strip("/")
    )
    try:
        resp = await client.post(
            f"https://api.apify.com/v2/acts/apify~instagram-profile-scraper/run-sync-get-dataset-items?token={APIFY_TOKEN}",
            json={"usernames": [username], "resultsLimit": 15},
            timeout=30.0,
        )
        items = resp.json()
        return items[0] if items and isinstance(items, list) else {}
    except Exception:
        return {}


async def gather_all_data(inputs: dict) -> dict:
    """
    Run all data-gathering tasks in parallel.
    Always runs: Exa searches (person articles, company news, LinkedIn web, competitors).
    Conditionally runs: Apify URL scrapes + Instagram if URLs provided.
    """
    name    = inputs["name"]
    company = inputs["company"]

    async with httpx.AsyncClient() as client:
        # Build task dict — keys become the gathered dict keys
        tasks = {
            "person_articles":      exa_search(client, f'"{name}" {company} interview article post blog 2024 2025'),
            "company_news":         exa_search(client, f'{company} news funding product launch milestone 2024 2025'),
            "person_background":    exa_search(client, f'"{name}" {company} background experience LinkedIn education'),
            "competitor_landscape": exa_search(client, f'{company} competitors market landscape industry analysis'),
            "person_social":        exa_search(client, f'"{name}" opinion thought leadership writing published'),
        }

        if inputs.get("linkedin"):
            tasks["linkedin_page"] = apify_scrape_url(client, inputs["linkedin"])
        if inputs.get("website"):
            tasks["company_website"] = apify_scrape_url(client, inputs["website"])
        if inputs.get("instagram"):
            tasks["instagram_data"] = apify_instagram(client, inputs["instagram"])

        results = await asyncio.gather(*tasks.values(), return_exceptions=True)

    return {
        k: (None if isinstance(v, Exception) else v)
        for k, v in zip(tasks.keys(), results)
    }


# ── Prompt Engineering ─────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are a pre-meeting intelligence analyst — think CIA dossier meets executive coach.
You receive raw research data scraped from public sources about a person and their company.
Your job: analyse it through a psychological bias framework and output a structured meeting brief.

BIAS FRAMEWORK (apply in this priority order):
1. CONFIRMATION BIAS — find genuine overlaps: shared region, sports allegiances, business philosophy, life stage
2. RECENCY BIAS — what they've been publicly focused on in the last 30–90 days; their current mental model
3. AUTHORITY BIAS — who they reference, quote, or publicly admire; their intellectual heroes
4. IN-GROUP / TRIBAL BIAS — shared identity signals: alma mater, industry circles, communities, peer groups
5. LOSS AVERSION — what they're most afraid of losing right now: competitive position, growth targets, team, reputation
6. ANCHORING + SOCIAL PROOF — the single most powerful anchor for the meeting; mutual connections or credibility signals

CONVERSATION CASCADE RULES:
Each cascade must:
- Start from a specific, real research signal (not generic)
- Open with a curious, non-interrogating question that feels earned
- Map where the thread leads (what pain or priority it will reveal)
- Bridge back to an execution gap the meeting attendee can fill
The goal: natural conversation that opens a pitch angle, not an interrogation.

WRITING STYLE:
- Be specific and sharp. "He referenced Taleb 3× this month" > "He is interested in risk management"
- Never write generic corporate observations
- Infer intelligently when data is sparse — but flag inferences clearly
- Quick Fire bullets must be punchy, specific, and immediately actionable

OUTPUT: Valid JSON only. No text before or after. Match this schema exactly:

{
  "person": {
    "name": "string",
    "role": "string",
    "company": "string",
    "location": "string or null",
    "initials": "2-char string"
  },
  "meetingType": "string",
  "data_quality": "high | medium | low",
  "confirmation_bias": [
    { "label": "string (specific, grounded in data)", "type": "Region | Sports | Business | Education | Life Stage", "strength": "high | medium | low" }
  ],
  "recency_signals": [
    { "signal": "string (specific, dated if possible)", "urgency": "hot | medium | watch" }
  ],
  "authority_anchors": [
    { "name": "string", "theme": "string" }
  ],
  "ingroup_markers": ["string"],
  "loss_aversion": [
    { "fear": "string (specific, inferred from data)", "implication": "string (how this should shape your approach)" }
  ],
  "cascades": [
    {
      "id": 1,
      "seed": "string (topic label)",
      "strength": "high | medium",
      "opening": "string (the exact question to open with, written in quotes)",
      "thread": "string (where this conversation leads and what it will reveal)",
      "bridge": "string (how this connects to the meeting attendee's offering or pitch angle)"
    }
  ],
  "anchor": {
    "main": "string (the one thing to anchor the entire meeting on — specific and bold)",
    "social_proof": "string (mutual connections, credibility signals, or shared community proof points)"
  },
  "content_analysis": {
    "frequency": "string (estimated posting cadence)",
    "assessment": "string (one-line read on their content intent)",
    "themes": ["string"],
    "style": "string (how they write/communicate and what it means for how YOU should communicate with them)",
    "sponsored": true or false,
    "sponsoredNote": "string or null"
  },
  "quick_fire": [
    "string (5 punchy bullets — the only things you need if you have 5 minutes)"
  ]
}"""


def build_user_prompt(inputs: dict, gathered: dict) -> str:
    name         = inputs["name"]
    company      = inputs["company"]
    role         = inputs.get("role", "")
    meeting_type = inputs.get("meetingType", "Sales Pitch")
    time_avail   = inputs.get("timeAvail", "24hr")
    context      = inputs.get("context", "")
    is_followup  = inputs.get("isFollowUp", False)
    prev_anchored= inputs.get("prevAnchored", "")
    prev_attend  = inputs.get("prevAttendees", "")

    lines = [
        "Generate a meeting intelligence brief for this meeting.",
        "",
        "MEETING DETAILS:",
        f"  Person:        {name}" + (f", {role}" if role else "") + f" at {company}",
        f"  Meeting Type:  {meeting_type}",
        f"  Prep Time:     {time_avail}",
        f"  Stage:         {'Follow-up meeting' if is_followup else 'First meeting'}",
    ]
    if is_followup and prev_attend:
        lines.append(f"  Last meeting:  Attended by {prev_attend}")
    if is_followup and prev_anchored:
        lines.append(f"  Last anchor:   {prev_anchored}")
    if context:
        lines.append(f"  Context:       {context}")

    lines += ["", "─── RESEARCH DATA ───────────────────────────────────────────────────"]

    def add_section(title, items, key="text", max_items=5, max_chars=600):
        if not items:
            return
        lines.append(f"\n### {title}")
        for r in (items[:max_items] if isinstance(items, list) else []):
            if isinstance(r, dict):
                t = r.get("title", "")
                u = r.get("url", "")
                body = r.get(key, "")[:max_chars]
                lines.append(f"  [{t}]({u})\n  {body}")

    add_section("Recent Articles & Activity (Person)", gathered.get("person_articles"))
    add_section("Company News & Milestones",            gathered.get("company_news"))
    add_section("Background & LinkedIn Signals",        gathered.get("person_background"))
    add_section("Thought Leadership & Social Writing",  gathered.get("person_social"))
    add_section("Competitor & Market Landscape",        gathered.get("competitor_landscape"))

    if gathered.get("linkedin_page"):
        lines.append(f"\n### LinkedIn Profile (scraped)\n{gathered['linkedin_page'][:2500]}")

    if gathered.get("company_website"):
        lines.append(f"\n### Company Website\n{gathered['company_website'][:2500]}")

    ig = gathered.get("instagram_data")
    if ig:
        lines.append("\n### Instagram Profile")
        lines.append(f"  Bio:       {ig.get('biography', 'n/a')}")
        lines.append(f"  Followers: {ig.get('followersCount', 'n/a')}")
        for post in ig.get("latestPosts", [])[:8]:
            cap = post.get("caption", "")[:200]
            if cap:
                lines.append(f"  Post: {cap}")

    lines += [
        "",
        "─────────────────────────────────────────────────────────────────────",
        f"Now generate the complete meeting brief JSON for {name} at {company}.",
    ]

    return "\n".join(lines)


# ── Flask Route ────────────────────────────────────────────────────────────────

@app.route("/api/brief", methods=["POST", "OPTIONS"])
def generate_brief():
    if request.method == "OPTIONS":
        return "", 200

    inputs = request.get_json(force=True)
    if not inputs or not inputs.get("name") or not inputs.get("company"):
        return jsonify({"error": "name and company are required"}), 400

    # 1. Gather data in parallel
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        gathered = loop.run_until_complete(gather_all_data(inputs))
    finally:
        loop.close()

    # 2. Build prompt
    user_prompt = build_user_prompt(inputs, gathered)

    # 3. Generate brief with Claude
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    message = client.messages.create(
        model="claude-opus-4-6",
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
    )

    raw = message.content[0].text.strip()

    # Strip markdown code fences if Claude wraps in ```json
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)

    brief = json.loads(raw)
    return jsonify(brief)


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    app.run(debug=True, port=5001)
