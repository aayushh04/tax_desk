# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Two audiences, weighted equally:

- **Analysts at a small Indian tax consultancy** (CA firm staff) who spend hours on GST reconciliation, regime comparisons and capital-gains working by hand. They use the tool repeatedly during the working week, on office laptops/desktops in daylight, and need to trust every figure before it goes to a client or the GST portal.
- **Finance interviewers and recruiters** opening the live demo link for a minute or two to judge the builder (a final-year B.Tech AI student). They need to see real work happen immediately and come away believing the tool would survive a real firm.

## Product Purpose

TaxDesk prepares the repetitive working papers of a small tax practice: it reconciles a purchase register with GSTR-2B, compares the old and new income-tax regimes for a salaried client, and computes mutual fund capital gains with FIFO and grandfathering. It exports formatted Excel, a client PDF and supplier email drafts. Success: an analyst finishes in minutes what took an afternoon, and an interviewer understands the tool and its tax logic from one visit.

## Positioning

Built from a real internship's workload by someone who did that work by hand: Indian tax specifics (GSTIN check characters, ITC at risk, marginal relief above Rs 12 lakh, 31 Jan 2018 grandfathering, ITA 2025 section numbers shown with their old numbers) handled with the care of a working paper, and every rule traceable to one sourced rules file.

## Operating Context

- Inputs: purchase-register and GSTR-2B Excel/CSV exports (messy, portal-shaped), salary and deduction figures, MF transaction CSVs or CAMS/KFintech CAS PDFs.
- Outputs reviewed before use: Excel workbooks, a one-page client PDF, copy-paste email drafts.
- Human in the loop: the app prepares, flags and exports; it never files on any government portal or sends email.
- Seen mostly on laptops/desktops in daytime office conditions; phone views are secondary but must work.

## Capabilities and Constraints

- Stack: Streamlit multi-page app (Home.py + pages/), pure-Python logic in taxdesk/, deployed free on Streamlit Community Cloud. Design work stays inside Streamlit (theme, CSS, layout, components).
- Tax year 2026-27 rules live only in config/tax_rules_2026_27.yaml.
- Uploaded files are processed in memory only; PANs are always masked (ABCDE****F).
- Footer on every page: "Educational project. Not tax advice. Verify all figures before filing."
- Out of scope: surcharge, senior-citizen slabs, business income.

## Evidence on Hand

- Synthetic data only (taxdesk/sample_data.py): 30 fake suppliers, 200 invoices with 29 planted problems, 3 fake salaried clients, a 2016-2026 MF history. Never use or invent real client data.
- Real measured facts: 79 passing tests; 5,200 invoices reconcile in about 0.8 s.
- No testimonials, firm logos, users or adoption claims exist; none may be invented.

## Product Principles

1. Every figure is traceable: show the working, the rule, and where the number came from.
2. Prepare, never decide: flag and explain; the human reviews and acts.
3. Show the work happening: the first thing anyone sees should be the tool doing its job on real-looking data.
4. Indian practice conventions first: lakh/crore grouping, dd-mm-yyyy, new section numbers with the old in brackets.
5. Privacy by default: in-memory processing, masked identifiers, synthetic demo data.
