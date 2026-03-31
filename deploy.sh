#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# Meeting Prepper — One-shot Vercel deploy script
# Run this once from the meeting-prepper folder on your machine.
# ─────────────────────────────────────────────────────────────────────────────
set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo ""
echo "🧠  Meeting Prepper — Vercel Deploy"
echo "════════════════════════════════════"

# ── 1. Check Node.js ──────────────────────────────────────────────────────────
if ! command -v node &> /dev/null; then
  echo -e "${RED}✗ Node.js not found.${NC}"
  echo "  Install it from https://nodejs.org (LTS version) then re-run this script."
  exit 1
fi
echo -e "${GREEN}✓ Node.js $(node -v)${NC}"

# ── 2. Install Vercel CLI ─────────────────────────────────────────────────────
if ! command -v vercel &> /dev/null; then
  echo "  Installing Vercel CLI..."
  npm install -g vercel --silent
fi
echo -e "${GREEN}✓ Vercel CLI $(vercel --version 2>/dev/null | head -1)${NC}"

# ── 3. Load .env ──────────────────────────────────────────────────────────────
if [ ! -f ".env" ]; then
  echo -e "${RED}✗ .env file not found. Make sure you're running from the meeting-prepper folder.${NC}"
  exit 1
fi
export $(grep -v '^#' .env | xargs)
echo -e "${GREEN}✓ .env loaded${NC}"

# ── 4. Vercel login ───────────────────────────────────────────────────────────
echo ""
echo -e "${YELLOW}→ Logging into Vercel (a browser window will open)...${NC}"
vercel login

# ── 5. Link / initialise project ─────────────────────────────────────────────
echo ""
echo -e "${YELLOW}→ Linking project to Vercel...${NC}"
vercel link --yes --project meeting-prepper

# ── 6. Set environment variables ─────────────────────────────────────────────
echo ""
echo -e "${YELLOW}→ Setting environment variables...${NC}"

set_env() {
  local key=$1
  local val=$2
  # Remove existing (ignore errors), then add fresh
  vercel env rm "$key" production --yes 2>/dev/null || true
  echo "$val" | vercel env add "$key" production
  echo -e "  ${GREEN}✓ $key${NC}"
}

set_env "ANTHROPIC_API_KEY" "$ANTHROPIC_API_KEY"
set_env "EXA_API_KEY"       "$EXA_API_KEY"
set_env "APIFY_TOKEN"       "$APIFY_TOKEN"

# ── 7. Deploy ─────────────────────────────────────────────────────────────────
echo ""
echo -e "${YELLOW}→ Deploying to production...${NC}"
vercel --prod --yes

echo ""
echo -e "${GREEN}════════════════════════════════════${NC}"
echo -e "${GREEN}✅  Done! Your app is live.${NC}"
echo -e "${GREEN}════════════════════════════════════${NC}"
echo ""
echo "Next steps:"
echo "  1. Open the URL above and test with a real name + company"
echo "  2. Rotate your API keys at:"
echo "       console.anthropic.com → API Keys"
echo "       dashboard.exa.ai/api-keys"
echo "       console.apify.com → Settings → Integrations"
echo ""
