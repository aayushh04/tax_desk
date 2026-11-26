---
version: 1
slug: "pages-1-gst-reconciliation-py"
primary_target: "pages/1_GST_Reconciliation.py"
related_targets: ["Home.py","pages/2_ITR_Regime_Comparison.py","pages/3_MF_Capital_Gains.py","ui_common.py"]
---

# TaxDesk app surfaces (Home, GST, ITR, MF)

Scope: the whole Streamlit app. Visitor mode: Operate. Audiences: CA firm analysts doing the work weekly on daytime office laptops, and interviewers judging the demo in one or two minutes. Task: load data, confirm columns or inputs, read results, export. Constraints: stays in Streamlit (theme, CSS, standard widgets); PANs masked; footer disclaimer on every page; synthetic data only. Replaces the earlier Audit File world at the user's request ("change the entire design").

## Direction contract

THESIS: Each module is a financial statement whose figures carry Note numbers that open their working, like an annual report's statements and Notes to Accounts. It refuses the fintech dashboard of KPI cards, donut charts and a blue accent.

OWN-WORLD: Report-navy sidebar (#14213D) binding a cool grey ground (#F3F5F8) with white statement sheets on #D5DBE5 hairlines. Source Serif 4 for titles, statement names and note headings; Public Sans for everything else, tabular figures. Ochre (#C98A12, text #8F5E06) for note references and items to review; red #B42318 only for money at risk; green #1F7A4D for agreed and the cheaper regime's total. Square 2px corners, no shadows, deductions in brackets, totals double-ruled.

STORY: The analyst opens a module, loads files, and reads a statement (Particulars, Note, Amount) whose bottom lines say what is at risk; a note number jumps to the invoices or working behind it; they export and sign the approval block. An interviewer reads the statement and callout alone and understands the result.

FIRST VIEWPORT: Navy sidebar nav; serif page title with subtitle left, client and period right, hairline beneath. Left column: the statement in a white sheet with ochre note numbers and the red ITC-at-risk line. Right column: the callout with the headline figure (red at risk, green saving) and status chips, then Download Excel as the primary action.

FORM: Notes to Accounts, IMPECCABLE'S PICK (my rank 1 of 7 grounded candidates; the roll assigned rank 6, Scorecard). seed:5979125161b58902. Signature move: ochre note references in every statement linking to numbered note sections (#note-n) that hold the working tables.

FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance
