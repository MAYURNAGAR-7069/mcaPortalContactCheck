# Company Contact Finder — Groq + Gemini

## Features
- Upload company master CSV or Excel.
- Uses Company Name, CIN, registered address, PIN code and state.
- Choose Groq browser search, Gemini Google Search grounding, or run both and compare.
- Crawls public pages on the candidate official website for visible emails and phone numbers.
- Exports CSV and Excel, with source URLs and status.

## Install and run on Ubuntu/Linux
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```
Open the local URL printed by Streamlit (usually http://localhost:8501).

## API keys
- Groq: create/manage an API key in the Groq console.
- Gemini: create/manage an API key in Google AI Studio.
- Enter keys in the sidebar at runtime; they are not saved into the source file.
- A consumer subscription does not necessarily include API usage; API access and billing/quotas may be separate. Check your account's API access and current pricing.
- Groq browser search requires a model that supports the built-in browser_search tool. This app uses `openai/gpt-oss-20b`.

## Important
- The app processes up to 50 companies per run to control API use.
- Search may be incomplete or rate-limited. Review source URLs and manually verify details.
- Only collect public business contact information, respect site terms/access controls and applicable privacy/marketing rules.
- Never treat AI output as verified unless a source supports it.
