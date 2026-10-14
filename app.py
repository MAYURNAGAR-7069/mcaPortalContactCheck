import io, re, json, time
from urllib.parse import urljoin, urlparse
import pandas as pd
import requests
import streamlit as st
from bs4 import BeautifulSoup
from ddgs import DDGS

st.set_page_config(page_title="Company Contact Finder v2", page_icon="🔎", layout="wide")
st.title("🔎 Company Contact Finder — v2")
st.caption("Uses company name + CIN + address/state to identify the right company and collect publicly listed business contacts.")
st.info("Contacts are leads, not guaranteed verified. Check source URLs before outreach and follow website terms, rate limits, and applicable privacy/marketing rules.")

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; CompanyContactFinder/2.0; contact discovery)"}
EMAIL_RE = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
# Prioritize Indian landline/mobile formats; do not accept arbitrary 7-15 digit fragments from page text.
INDIA_PHONE_RE = re.compile(r"(?<!\w)(?:(?:\+91|0091|91)[\s().-]*)?(?:0[\s().-]*)?(?:[6-9]\d{9}|[1-9]\d{1,4}[\s().-]+\d{5,8})(?!\w)")
SKIP_DOMAINS = (
    "linkedin.com", "facebook.com", "instagram.com", "x.com", "twitter.com",
    "youtube.com", "crunchbase.com", "justdial.com", "indiamart.com",
    "zaubacorp.com", "tofler.in", "thecompanycheck.com", "glassdoor.com",
    "wikipedia.org", "tracxn.com", "sulekha.com"
)
CONTACT_WORDS = ("contact", "about", "support", "reach-us", "reachus", "connect", "enquiry", "inquiry")
DIRECTORY_HINTS = ("directory", "company-details", "company-profile", "business-listing")

def norm(s):
    return re.sub(r"\s+", " ", str(s or "")).strip()

def host_of(url):
    return urlparse(url).netloc.lower().removeprefix("www.")

def is_skipped(url):
    h = host_of(url)
    return any(d in h for d in SKIP_DOMAINS)

def clean_url(url):
    url = norm(url)
    if not url:
        return ""
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    return url

def query_search(query, region="in-en", max_results=8):
    rows = []
    try:
        with DDGS() as ddgs:
            for r in ddgs.text(query, region=region, max_results=max_results):
                u = r.get("href") or r.get("url") or ""
                if u.startswith("http"):
                    rows.append({"url": u, "title": norm(r.get("title")), "body": norm(r.get("body"))})
    except Exception as e:
        return [], str(e)
    return rows, ""

def domain_company_score(item, company, cin, address, state):
    url, title, body = item["url"], item["title"].lower(), item["body"].lower()
    host = host_of(url)
    company_words = [w.lower() for w in re.findall(r"[A-Za-z0-9]+", company) if len(w) > 2]
    score = 0
    if not is_skipped(url): score += 2
    if any(w in host for w in company_words[:4]): score += 5
    if any(w in title for w in company_words): score += 3
    if cin and cin.lower() in (title + " " + body): score += 8
    addr_words = [w.lower() for w in re.findall(r"[A-Za-z0-9]+", address) if len(w) > 3]
    if any(w in body for w in addr_words[:5]): score += 2
    if state and state.lower() in (title + " " + body): score += 1
    if any(x in url.lower() for x in DIRECTORY_HINTS): score -= 3
    if any(x in title for x in ("linkedin", "facebook", "instagram", "justdial", "india mart")): score -= 10
    return score

def choose_website(results, company, cin, address, state):
    candidates = [r for r in results if not is_skipped(r["url"])]
    if not candidates:
        return "", 0, ""
    ranked = sorted(candidates, key=lambda r: domain_company_score(r, company, cin, address, state), reverse=True)
    best = ranked[0]
    score = domain_company_score(best, company, cin, address, state)
    # Only claim as likely official when it has meaningful company/domain evidence.
    confidence = "Likely official" if score >= 7 else "Needs review"
    return best["url"], score, confidence

def fetch_page(url, timeout=10):
    try:
        resp = requests.get(url, headers=HEADERS, timeout=timeout, allow_redirects=True)
        if resp.status_code >= 400:
            return None, f"HTTP {resp.status_code}"
        if "text/html" not in resp.headers.get("content-type", "").lower():
            return None, "Not HTML"
        return resp.text[:2_000_000], ""
    except Exception as e:
        return None, str(e)[:160]

def phone_clean(raw):
    raw = norm(raw).strip(" .,-|")
    digits = re.sub(r"\D", "", raw)
    if digits.startswith("0091"): digits = digits[4:]
    elif digits.startswith("91") and len(digits) >= 12: digits = digits[2:]
    if digits.startswith("0") and len(digits) == 11: digits = digits[1:]
    if len(digits) == 10 and digits[0] in "6789":
        return "+91 " + digits
    # Indian landlines can vary; preserve only plausible lengths.
    if 7 <= len(digits) <= 11:
        return raw
    return ""

def extract_page(html, page_url):
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(" ", strip=True)
    emails = set(EMAIL_RE.findall(html.replace("[at]", "@").replace("(at)", "@")))
    emails.update(EMAIL_RE.findall(text))
    for a in soup.select('a[href^="mailto:"]'):
        value = a.get("href", "").split(":",1)[-1].split("?",1)[0].strip()
        if EMAIL_RE.fullmatch(value): emails.add(value)
    phones = set()
    for a in soup.select('a[href^="tel:"]'):
        p = phone_clean(a.get("href","").split(":",1)[-1])
        if p: phones.add(p)
    for m in INDIA_PHONE_RE.findall(text):
        p = phone_clean(m)
        if p: phones.add(p)
    links = []
    for a in soup.find_all("a", href=True):
        label = (a.get_text(" ", strip=True) + " " + a["href"]).lower()
        if any(w in label for w in CONTACT_WORDS):
            u = urljoin(page_url, a["href"]).split("#")[0]
            if urlparse(u).scheme in ("http","https") and host_of(u) == host_of(page_url):
                links.append(u)
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    return emails, phones, list(dict.fromkeys(links)), title, text[:12000]

def gemini_search(company, cin, address, state, api_key):
    try:
        from google import genai
        from google.genai import types
        client = genai.Client(api_key=api_key)
        prompt = f"""
Find the official website and publicly listed business contact details for this exact Indian company.
Company name: {company}
CIN: {cin or 'not provided'}
Registered address: {address or 'not provided'}
State: {state or 'not provided'}

Use Google Search grounding. Prefer the company's own website and official/credible sources.
Do not invent or infer email addresses or phone numbers. If not found, return an empty string.
Return ONLY valid JSON with keys:
official_website, emails (array), phone_numbers (array), source_urls (array), notes.
Include sources that directly support each contact if possible. Distinguish official website from directory pages.
"""
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
            config=types.GenerateContentConfig(
                tools=[types.Tool(google_search=types.GoogleSearch())],
                response_mime_type="application/json"
            )
        )
        data = json.loads(response.text or "{}")
        return data, ""
    except Exception as e:
        return {}, f"Gemini search failed: {str(e)[:220]}"

def scan_company(row, region, pages_per_site, mode, api_key):
    company = norm(row.get("Company Name") or row.get("Company") or "")
    cin = norm(row.get("CIN"))
    address = norm(row.get("Company Address") or row.get("Address"))
    state = norm(row.get("Company State") or row.get("State"))
    pincode = norm(row.get("Pin Code") or row.get("Pincode"))
    context = ", ".join(x for x in [address, pincode, state] if x)

    if mode == "Gemini Search (API key required)" and api_key:
        gd, err = gemini_search(company, cin, context, state, api_key)
        if not err:
            website = clean_url(gd.get("official_website", ""))
            emails = [norm(x).lower() for x in gd.get("emails", []) if EMAIL_RE.fullmatch(norm(x))]
            phones = [phone_clean(x) for x in gd.get("phone_numbers", [])]
            phones = [x for x in phones if x]
            sources = [clean_url(x) for x in gd.get("source_urls", []) if str(x).startswith("http")]
            # Crawl official website and contact pages as a second check.
            if website:
                urls = [website]
                for u in list(urls):
                    html, _ = fetch_page(u)
                    if html:
                        pe, pp, links, _, _ = extract_page(html, u)
                        emails.extend(pe); phones.extend(pp)
                        for link in links:
                            if len(urls) < pages_per_site and link not in urls: urls.append(link)
                for u in urls[1:]:
                    html, _ = fetch_page(u)
                    if html:
                        pe, pp, _, _, _ = extract_page(html, u)
                        emails.extend(pe); phones.extend(pp)
                        sources.append(u)
            return make_result(company, cin, address, website, emails, phones, sources, "Gemini grounded search", gd.get("notes",""))
        # If Gemini fails, don't silently disguise it as a valid result; fall through to free search.
        gemini_error = err
    else:
        gemini_error = ""

    queries = [
        f'"{company}" "{cin}" email phone',
        f'"{company}" "{cin}" official website',
        f'"{company}" "{address}" contact email phone',
        f'"{company}" "{state}" official website contact',
        f'"{company}" email phone India'
    ]
    if pincode:
        queries.insert(0, f'"{company}" "{pincode}" email phone website')
    all_results, errors = [], []
    for q in queries:
        found, error = query_search(q, region, 7)
        all_results.extend(found)
        if error: errors.append(error)
        time.sleep(0.35)
    seen, unique = set(), []
    for item in all_results:
        key = item["url"].split("#")[0]
        if key not in seen:
            seen.add(key); unique.append(item)
    website, score, confidence = choose_website(unique, company, cin, context, state)
    emails, phones, sources = set(), set(), []
    # Include evidence found in result snippets, but retain URLs as sources.
    for item in unique:
        emails.update(EMAIL_RE.findall(item["title"] + " " + item["body"]))
        for m in INDIA_PHONE_RE.findall(item["title"] + " " + item["body"]):
            p = phone_clean(m)
            if p: phones.add(p)
    # Crawl the highest-ranked domain only; never assume arbitrary result URL is official.
    if website:
        base_host = host_of(website)
        urls = [website]
        for item in sorted(unique, key=lambda x: domain_company_score(x, company, cin, context, state), reverse=True):
            if host_of(item["url"]) == base_host and any(w in item["url"].lower() for w in CONTACT_WORDS):
                if item["url"] not in urls: urls.append(item["url"])
        idx = 0
        while idx < len(urls) and idx < pages_per_site:
            u = urls[idx]; idx += 1
            html, err = fetch_page(u)
            if not html: continue
            pe, pp, links, _, _ = extract_page(html, u)
            emails.update(pe); phones.update(pp); sources.append(u)
            for link in links:
                if link not in urls and len(urls) < pages_per_site: urls.append(link)
            time.sleep(0.25)
    status = "Found contacts" if emails or phones else "No public contacts detected"
    if not website: status = "Official website not confidently identified"
    if errors and not unique: status = "Search provider error: " + errors[0][:120]
    if gemini_error: status += " (Gemini unavailable; used free search)"
    return make_result(company, cin, address, website, emails, phones, sources + [x["url"] for x in unique[:8]], status, f"Website confidence: {confidence}; score={score}")

def make_result(company, cin, address, website, emails, phones, sources, status, notes=""):
    cleaned_emails = sorted({e.strip(".,;:()[]<>").lower() for e in emails if EMAIL_RE.fullmatch(e.strip(".,;:()[]<>")) and "example." not in e.lower()})
    cleaned_phones = sorted(set(p for p in phones if p))
    return {
        "Company Name": company, "CIN": cin, "Registered Address": address,
        "Website": website, "Emails": "; ".join(cleaned_emails),
        "Phone numbers": "; ".join(cleaned_phones),
        "Source URLs": "; ".join(dict.fromkeys(s for s in sources if s)),
        "Status / confidence": status, "Notes": notes
    }

with st.sidebar:
    st.header("Search settings")
    mode = st.radio("Search method", ["Free web search (DDGS)", "Gemini Search (API key required)"])
    api_key = ""
    if mode == "Gemini Search (API key required)":
        api_key = st.text_input("Gemini API key", type="password", help="Use a Google AI Studio API key. API usage may incur charges.")
        st.caption("The app uses Google Search grounding through Gemini when available.")
    region_label = st.selectbox("Search region", ["India", "Worldwide"], index=0)
    region = "in-en" if region_label == "India" else "wt-wt"
    pages_per_site = st.slider("Maximum pages to check per company website", 1, 6, 5)

st.subheader("Upload your company master file")
st.write("Your file's `Company Name`, `CIN`, `Company Address`, `Pin Code`, and `Company State` columns are supported.")
upload = st.file_uploader("Upload CSV or Excel", type=["csv", "xlsx"])
manual = st.text_area("Or enter company names (one per line)", placeholder="SPARKIT KNITS PRIVATE LIMITED")
input_df = None
if upload is not None:
    try:
        if upload.name.lower().endswith(".csv"):
            input_df = pd.read_csv(upload, dtype=str).fillna("")
        else:
            input_df = pd.read_excel(upload, dtype=str).fillna("")
        st.success(f"Loaded {len(input_df)} rows and {len(input_df.columns)} columns.")
        st.dataframe(input_df.head(5), use_container_width=True)
    except Exception as e:
        st.error(f"Could not read file: {e}")

rows = []
if input_df is not None:
    lower = {str(c).strip().lower(): c for c in input_df.columns}
    company_col = lower.get("company name") or lower.get("company")
    if not company_col:
        st.error("Could not find a 'Company Name' or 'Company' column.")
    else:
        for _, r in input_df.iterrows():
            d = {str(k): norm(v) for k, v in r.to_dict().items()}
            d["Company Name"] = norm(r.get(company_col, ""))
            rows.append(d)
if manual.strip():
    for name in [norm(x) for x in manual.splitlines() if norm(x)]:
        rows.append({"Company Name": name})
# de-dupe by CIN where available, otherwise normalized company name
deduped, seen = [], set()
for r in rows:
    key = norm(r.get("CIN")) or norm(r.get("Company Name")).lower()
    if key and key not in seen:
        seen.add(key); deduped.append(r)
rows = deduped
st.caption(f"Companies ready: {len(rows)}")

if st.button("Find company contacts", type="primary", disabled=not rows):
    if mode == "Gemini Search (API key required)" and not api_key:
        st.error("Enter a Gemini API key, or choose Free web search.")
    else:
        results = []
        progress = st.progress(0)
        status_line = st.empty()
        for i, row in enumerate(rows[:100]):
            nm = row.get("Company Name", "")
            status_line.write(f"Searching {i+1}/{min(len(rows),100)}: **{nm}**")
            try:
                results.append(scan_company(row, region, pages_per_site, mode, api_key))
            except Exception as e:
                results.append(make_result(nm, norm(row.get("CIN")), norm(row.get("Company Address")), "", [], [], [], "Error: " + str(e)[:180]))
            progress.progress((i+1)/min(len(rows),100))
        st.session_state["contact_results_v2"] = pd.DataFrame(results)
        status_line.success("Search finished. Verify contacts using the source URLs.")
        if len(rows) > 100:
            st.warning("This run processed the first 100 companies. Split the file into smaller batches.")

if "contact_results_v2" in st.session_state:
    out = st.session_state["contact_results_v2"]
    st.subheader("Contact results")
    st.dataframe(out, use_container_width=True, hide_index=True)
    st.download_button("Download CSV", out.to_csv(index=False).encode("utf-8-sig"), "company_contacts_v2.csv", "text/csv")
    b = io.BytesIO()
    with pd.ExcelWriter(b, engine="openpyxl") as writer:
        out.to_excel(writer, index=False, sheet_name="Contacts")
    st.download_button("Download Excel", b.getvalue(), "company_contacts_v2.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

st.divider()
st.caption("Free search depends on public search results and may be rate-limited. Gemini mode requires a Google AI Studio API key and can have usage costs. Neither method guarantees a public email or phone for every company.")
