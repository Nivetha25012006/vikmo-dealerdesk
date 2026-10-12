# VIKMO DealerDesk — AI / ML Intern Track

**Track:** `aiml` (AI / ML Intern Track)  
**Submission:** Complete implementation of Backend Core, Dealer Assistant (GenAI with Tool Calling), Demand Forecasting & Reorder Suggestions (ML), Automated Test Suite, and Dealer Portal Frontend UI.

- **Public Repository Link:** `https://github.com/Nivetha25012006/vikmo-dealerdesk`
- **5-Minute Video Walkthrough:** `https://youtu.be/placeholder-video-link` *(Unlisted YouTube / Loom link)*

---

## 1. Project Overview & Architecture

VIKMO DealerDesk is an intelligent spare parts ordering, inventory management, and demand forecasting platform for South Indian automotive and motorcycle distributors.

```
                  ┌────────────────────────────────────────┐
                  │   Dealer Dashboard UI (SPA at /)       │
                  └───────────────────┬────────────────────┘
                                      │ REST / JSON
                                      ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│                            Django REST Framework API                         │
│                                                                              │
│  /api/health/            /api/products/          /api/inventory/{sku}/       │
│  /api/dealers/           /api/orders/            /api/assistant/chat/        │
│  /api/forecast/{sku}/    /api/reorder-suggestions/                          │
└───────────────┬─────────────────────┬───────────────────────────┬────────────┘
                │                     │                           │
                ▼                     ▼                           ▼
┌──────────────────────────┐ ┌──────────────────────┐ ┌────────────────────────┐
│     PostgreSQL Engine    │ │  Dealer Assistant    │ │ Forecasting Engine     │
│  • Product Catalogue     │ │  • Gemini 2.5 Flash  │ │  • HistGradientBoost   │
│  • Inventory (Stock Lock)│ │  • Tool Calling      │ │  • Chronological Split │
│  • Dealer Accounts       │ │    - search_parts    │ │  • 160-row Forecast   │
│  • DRAFT Orders & Items  │ │    - check_stock     │ │  • Reorder Formulas    │
│  • Concurrency Safety    │ │    - create_draft    │ │  • Live Stock Safety   │
└──────────────────────────┘ └──────────────────────┘ └────────────────────────┘
```

---

## 2. Environment Variables & Setup

DealerDesk requires **PostgreSQL**. Copy `.env.example` to `.env` and configure your credentials:

```bash
cp .env.example .env
```

### Environment Variables Reference

| Variable | Description | Example / Default |
|---|---|---|
| `DATABASE_URL` | PostgreSQL connection URL (**PostgreSQL only**) | `postgres://user:pass@localhost:5432/dealerdesk` |
| `DJANGO_SECRET_KEY` | Secret key for Django | `dev-only-insecure-key` |
| `DJANGO_DEBUG` | Enable debug mode | `1` |
| `GEMINI_API_KEY` | Google Gemini API key (Primary LLM) | `AIzaSy...` |
| `GEMINI_MODEL` | Gemini model name | `gemini-2.5-flash` |
| `GROQ_API_KEY` | Groq API key (Alternative LLM) | `gsk_...` |
| `GROQ_MODEL` | Groq model name | `llama-3.3-70b-versatile` |
| `OPENAI_API_KEY` | OpenAI API key (Fallback) | `sk-...` |

> [!NOTE]
> For unit tests and offline environments without external LLM keys, a robust grounded deterministic assistant executes live database queries and formats answers in the exact contract schema.

---

## 3. Installation & Run Instructions

```bash
# 1. Create and activate a Python 3.11+ virtual environment
python -m venv .venv
# Linux / macOS:
source .venv/bin/activate
# Windows:
.venv\Scripts\activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Apply database migrations
python manage.py migrate --noinput

# 4. Seed initial catalogue (600 products) and dealers (25 dealers)
# Safe and idempotent to run twice (preserves live inventory)
python manage.py seed_data
python manage.py seed_data

# 5. Start the development server
python manage.py runserver 0.0.0.0:8000 --noreload
```

---

## 4. Testing & Verification

### Running Automated Test Suite

```bash
python manage.py test core ml
```

### Running the Official Smoke Test

With the server running on `http://localhost:8000`:

```bash
# Run smoke test for AI/ML track
python smoke_test.py --base-url http://localhost:8000 --track aiml

# Or run all checks
python smoke_test.py --base-url http://localhost:8000 --all
```

---

## 5. GenAI Dealer Assistant Details

- **Primary Provider:** Google Gemini
- **Model:** `gemini-3.8-flash` (configurable via `GEMINI_MODEL`)
- **Alternative Supported Providers:** Groq (`llama-3.3-70b-versatile`), OpenAI (`gpt-4o-mini`).
- **Tools Implemented:**
  1. `search_parts(query, vehicle, category)`: Live PostgreSQL search with vehicle fitment compatibility filters.
  2. `check_stock(sku)`: Fetches live available stock and current price from database.
  3. `create_draft_order(dealer_id, items)`: Creates a DRAFT order using core business logic and locks catalogue pricing.
- **Security & Grounding:**
  - System prompt classifies catalogue text as untrusted data to reject prompt injections.
  - LLMs cannot invent stock counts or prices; figures are anchored to PostgreSQL query results.
  - The assistant only creates `DRAFT` orders and asks clarifying questions when vehicle fitment is ambiguous.

---

## 6. Demand Forecasting & Reorder System

- **Target Horizon:** 4 future week-start dates (`2026-09-28`, `2026-10-05`, `2026-10-12`, `2026-10-19`) for all 40 SKUs in `data/lead_times.csv`.
- **Output:** [`ml/forecast.csv`](file:///c:/Users/nivet/Downloads/VIKMO_DealerDesk_Assignment%20%281%29/ml/forecast.csv) (exactly 160 rows).
- **Model:** `HistGradientBoostingRegressor` trained with chronological rolling-origin backtesting (zero future lookahead leakage).
- **Validation Comparison:**
  - *Last-Value Baseline:* MAE 12.26 | WAPE 35.30%
  - *Recent-Average (4-week) Baseline:* MAE 9.56 | WAPE 27.53%
  - *Same-Week-Last-Year Baseline:* MAE 11.77 | WAPE 33.89%
  - *HistGradientBoosting (Selected):* **MAE 6.25 | WAPE 17.99%**
- **Reorder Formula (Contract §10):**
  - $\text{Safety Stock} = \lceil 1.65 \times \sigma \times \sqrt{L} \rceil$ where $\sigma$ is the sample standard deviation ($n-1$) of the past 12 weeks of sales.
  - $\text{Reorder Point} = \text{Lead Time Demand} + \text{Safety Stock}$
  - $\text{Reorder Quantity} = \max(0, \lceil \text{Reorder Point} - \text{Current Stock} \rceil)$ using live database stock.

---

## 7. Dealer Portal Frontend UI

A single-page dashboard is accessible at the root URL:
`http://localhost:8000/`

Features:
1. **Overview Dashboard:** Total products count, dealer count, forecast SKU indicators.
2. **Product Catalogue:** Real-time search with vehicle fitment filter and live stock badges.
3. **Dealer Assistant:** Conversational chat interface showing tool execution calls, cited SKUs, and session persistence.
4. **Demand Forecast:** Interactive dropdown to view 4-week forecast per SKU.
5. **Reorder Suggestions:** Live table showing lead-time demand, safety stock, reorder point, and recommended reorder quantities.

---

## 8. Technical Decisions & FAQ

Detailed technical explanations for all 8 track questions are documented in [`DECISIONS.md`](file:///c:/Users/nivet/Downloads/VIKMO_DealerDesk_Assignment%20%281%29/DECISIONS.md).
