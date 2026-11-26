---
name: TaxDesk
description: Each module is a financial statement whose figures carry Note numbers that open their working.
colors:
  report-navy: "#14213D"
  cool-ground: "#F3F5F8"
  sheet-white: "#FFFFFF"
  statement-rule: "#D5DBE5"
  row-hairline: "#E6EAF0"
  table-hairline: "#E1E6EE"
  input-well: "#E9EDF3"
  slate-muted: "#5A6782"
  note-ochre: "#C98A12"
  note-ochre-text: "#8F5E06"
  review-tint: "#FBF4E6"
  risk-red: "#B42318"
  risk-border: "#E7A9A3"
  risk-tint: "#FCEFEE"
  agreed-green: "#1F7A4D"
  agreed-border: "#9CCBB2"
  agreed-tint: "#EEF7F2"
  binding-hover: "#1E2E52"
  binding-active: "#23365F"
  binding-edge: "#2A3B62"
  binding-text: "#C9D2E3"
  binding-caption: "#AEB9CF"
  selection-ochre: "#F5E3BC"
typography:
  display:
    fontFamily: "Source Serif 4, Georgia, serif"
    fontSize: "2.7rem"
    fontWeight: 700
    lineHeight: 1.1
  headline:
    fontFamily: "Source Serif 4, Georgia, serif"
    fontSize: "2.25rem"
    fontWeight: 700
    lineHeight: 1.15
    letterSpacing: "-0.01em"
  brand:
    fontFamily: "Source Serif 4, Georgia, serif"
    fontSize: "1.5rem"
    fontWeight: 700
  title:
    fontFamily: "Source Serif 4, Georgia, serif"
    fontSize: "1.3rem"
    fontWeight: 600
  note-title:
    fontFamily: "Source Serif 4, Georgia, serif"
    fontSize: "1.25rem"
    fontWeight: 600
  body:
    fontFamily: "Public Sans, sans-serif"
    fontSize: "1rem"
    fontWeight: 400
    fontFeature: "tnum"
  statement-body:
    fontFamily: "Public Sans, sans-serif"
    fontSize: "0.97rem"
    fontWeight: 400
    lineHeight: 1.4
    fontFeature: "tnum"
  caption:
    fontFamily: "Public Sans, sans-serif"
    fontSize: "0.9rem"
    fontWeight: 400
  label:
    fontFamily: "Public Sans, sans-serif"
    fontSize: "0.74rem"
    fontWeight: 600
    letterSpacing: "0.08em"
  field-label:
    fontFamily: "Public Sans, sans-serif"
    fontSize: "0.78rem"
    fontWeight: 400
    letterSpacing: "0.06em"
rounded:
  square: "2px"
spacing:
  chip-gap: "0.45rem"
  cell-y: "0.62rem"
  cell-x: "0.45rem"
  sm: "0.8rem"
  md: "1rem"
  sheet-x: "1.5rem"
  sheet-y: "1.25rem"
  note-gap: "2.3rem"
  note-close: "1.6rem"
  page-top: "2.4rem"
components:
  button-primary:
    backgroundColor: "{colors.report-navy}"
    textColor: "{colors.sheet-white}"
    rounded: "{rounded.square}"
  button-secondary:
    backgroundColor: "{colors.sheet-white}"
    textColor: "{colors.report-navy}"
    rounded: "{rounded.square}"
    height: "2.5rem"
    padding: "0 0.8rem"
  input-well:
    backgroundColor: "{colors.input-well}"
    textColor: "{colors.report-navy}"
    rounded: "{rounded.square}"
  nav-item:
    backgroundColor: "{colors.report-navy}"
    textColor: "{colors.binding-text}"
    rounded: "{rounded.square}"
    padding: "0.5rem 0.8rem"
  nav-item-hover:
    backgroundColor: "{colors.binding-hover}"
  nav-item-active:
    backgroundColor: "{colors.binding-active}"
    textColor: "{colors.sheet-white}"
  statement-sheet:
    backgroundColor: "{colors.sheet-white}"
    textColor: "{colors.report-navy}"
    typography: "{typography.statement-body}"
    padding: "1.25rem 1.5rem 1.1rem"
  statement-column-head:
    textColor: "{colors.slate-muted}"
    typography: "{typography.label}"
    padding: "0.5rem 0.45rem"
  note-reference:
    textColor: "{colors.note-ochre-text}"
    width: "3.6rem"
  callout:
    backgroundColor: "{colors.sheet-white}"
    textColor: "{colors.report-navy}"
    padding: "1.2rem 1.4rem 1.3rem"
  callout-figure:
    textColor: "{colors.report-navy}"
    typography: "{typography.display}"
  callout-figure-risk:
    textColor: "{colors.risk-red}"
  callout-figure-agreed:
    textColor: "{colors.agreed-green}"
  chip-neutral:
    backgroundColor: "{colors.sheet-white}"
    textColor: "{colors.report-navy}"
    rounded: "{rounded.square}"
    padding: "0.28rem 0.65rem"
  chip-agreed:
    backgroundColor: "{colors.agreed-tint}"
    textColor: "{colors.agreed-green}"
    rounded: "{rounded.square}"
    padding: "0.28rem 0.65rem"
  chip-review:
    backgroundColor: "{colors.review-tint}"
    textColor: "{colors.note-ochre-text}"
    rounded: "{rounded.square}"
    padding: "0.28rem 0.65rem"
  chip-risk:
    backgroundColor: "{colors.risk-tint}"
    textColor: "{colors.risk-red}"
    rounded: "{rounded.square}"
    padding: "0.28rem 0.65rem"
  note-heading-number:
    textColor: "{colors.note-ochre-text}"
    typography: "{typography.note-title}"
  note-heading-title:
    textColor: "{colors.report-navy}"
    typography: "{typography.note-title}"
  note-total:
    textColor: "{colors.report-navy}"
    typography: "{typography.body}"
    padding: "0.5rem 0.1rem 0.45rem"
  working-table-head:
    backgroundColor: "{colors.cool-ground}"
    textColor: "{colors.slate-muted}"
  approval-block:
    backgroundColor: "{colors.sheet-white}"
    textColor: "{colors.slate-muted}"
    typography: "{typography.field-label}"
    padding: "0.8rem 1rem 0.9rem"
---

# Design System: TaxDesk

## Overview

**Creative North Star: "Notes to Accounts"**

Every module reads like a page from an annual report. The working surface is a statement (Particulars, Note, Amount) set on a white sheet, and every figure that needs explaining carries an ochre Note number that jumps to a numbered note further down the page, where the invoices, lots or computation behind it sit in full tables. A report-navy sidebar binds the pages; the ground behind the sheets is a cool, quiet grey. The analyst reads the bottom lines first; the notes are there for the second, slower read.

The system is dense, flat and ruled, never decorated. Hierarchy comes from accounting convention rather than from colour blocks or cards: deductions sit in brackets, subtotals are ruled above, totals are ruled above and double-ruled below, and the one figure each statement exists to show is lifted into a callout beside it. Colour is semantic and scarce: ochre for note references and items to review, red only where money is at risk, green for agreed items and the cheaper regime's total. Two typefaces split the work: Source Serif 4 speaks for titles, statement names, note headings and the headline figure; Public Sans with tabular figures carries everything that is read or compared.

The world rejects the fintech dashboard: no row of KPI cards, no donut charts, no bright blue accent.

**Key Characteristics:**
- White statement sheets on a cool grey ground, bound by a report-navy sidebar.
- Ochre note numbers that link (#note-n) to numbered note sections holding the working.
- Accounting rules as structure: brackets for deductions, single rule over subtotals, double rule under totals.
- Serif for names and the headline figure, sans with tabular figures for every number in a table.
- Square 2px corners, hairline borders, no shadows.

## Colors

A navy-and-grey report palette with three semantic accents that each mean exactly one thing.

### Primary
- **Report Navy** (report-navy): the ink of the whole system. Body text, statement figures, titles, the primary button, focus rings, the rules over subtotals and totals, and the sidebar binding itself.

### Secondary
- **Note Ochre** (note-ochre, with note-ochre-text for type): note references in the Note column, the number in every note heading, and items that need review (review chips, "Difference" and "Needs review" status words, warning alerts). The brighter ochre is a border and stroke colour only; type in ochre always uses the darker note-ochre-text. Review Tint (review-tint) is its background wash and also the highlight on a targeted note heading.

### Tertiary
- **Risk Red** (risk-red, with risk-border and risk-tint): money at risk and nothing else. The risk line of a statement, a risk callout figure, risk chips, "Not in 2B" and "At risk" status words, error alerts.
- **Agreed Green** (agreed-green, with agreed-border and agreed-tint): agreed items, success alerts, a favourable callout figure, and the picked column's total (the cheaper regime) in a comparison statement.

### Neutral
- **Cool Ground** (cool-ground): the page background and dataframe header row.
- **Sheet White** (sheet-white): statement sheets, callouts, the approval block, contents rows, chips, secondary buttons, expanders.
- **Statement Rule** (statement-rule): the 1px border around every sheet, the hairline under the page header and note headings, chip and alert borders.
- **Row Hairline** (row-hairline) and **Table Hairline** (table-hairline): row separators inside statements and dataframe grid lines.
- **Input Well** (input-well): the fill of text inputs, selects and uploaders.
- **Slate Muted** (slate-muted): subtitles, captions, column heads, memo lines, approval field labels, the footer.
- **Binding tones** (binding-hover, binding-active, binding-edge, binding-text, binding-caption): the sidebar's hover and current-page fills, its divider, nav text and the caption under the TaxDesk name.
- **Selection Ochre** (selection-ochre): text selection, with navy text.

### Named Rules
**The One Meaning Rule.** Ochre means "see the note" or "review this"; red means "money at risk"; green means "agreed" or "the cheaper choice". No accent is ever used for decoration, emphasis or branding.

**The Red Is Money Rule.** Red appears only on a figure or line where tax credit or money is actually at risk. A validation message or a missing field is a review (ochre), not a risk.

## Typography

**Display Font:** Source Serif 4 (with Georgia, serif), self-hosted variable woff2
**Body Font:** Public Sans (with sans-serif), self-hosted variable woff2, latin-ext subset carries the rupee sign
**Label/Mono Font:** Streamlit's bundled monospace, only for the email drafts

**Character:** A bookish report serif paired with a plain public-service sans. The serif names things; the sans does the arithmetic. Tabular figures are set on the whole app, so every column of amounts aligns.

### Hierarchy
- **Display** (700, 2.7rem, 1.1; 2.1rem at 640px and below): the headline figure in a callout, such as ITC at risk or the regime saving. One per page. Source Serif 4 renders its own default figure style here, which reads as oldstyle against the lining sans figures in the statement.
- **Headline** (700, 2.25rem, 1.15, -0.01em; 1.8rem at 640px and below): the page title in the page header.
- **Brand** (700, 1.5rem): "TaxDesk" at the top of the sidebar.
- **Title** (600, 1.3rem): statement names ("Statement of input tax credit") and the Contents heading on Home.
- **Note title** (600, 1.25rem): note headings, number in ochre text and title in navy on one baseline.
- **Body** (400, 1rem, tabular figures): prose, subtitles, widget text. The home intro sheet caps at 72ch.
- **Statement body** (400, 0.97rem, 1.4; 0.88rem at 640px and below): statement rows. Subtotals 600, totals 700.
- **Caption** (400, 0.9rem to 0.95rem): callout captions, note heading counts, page-header meta.
- **Label** (600, 0.74rem, 0.08em, uppercase): statement column heads only (PARTICULARS, NOTE, AMOUNT (₹)).
- **Field label** (400, 0.78rem, 0.06em, uppercase): approval block field names (Prepared by, Reviewed by, Date).

### Named Rules
**The Serif Names, Sans Counts Rule.** Source Serif 4 is used for titles, statement names, note headings, the sidebar brand and the single callout figure. Every table figure, label and sentence is Public Sans with tabular figures.

**The Column Head Rule.** Tracked uppercase belongs to statement column heads and approval field labels, the places a printed report uses it. It is not used as an eyebrow above titles or sections.

**The Figure Grammar Rule.** Every figure is set in Indian grouping (13,00,328.88). Rupee amounts tracked in paise (GST credit, fund gains, costs, sale values) show 2 decimals, both in the statement and in the note tables. Computations that are rounded by law (the regime computation, income in slab, the estimated tax on gains) show whole rupees. Counts never show decimals, even in a 2-decimal statement column. NAVs and units show 4 places, similarity scores 1. Negatives in a table sit in brackets, like deductions in a statement. The ₹ sign goes on callout figures, note totals and amounts in sentences; table columns carry plain figures with "(₹)" in the column head.

## Layout

A wide Streamlit page capped at 1240px, with 2.4rem above the header. Every module opens the same way: a page header with title and subtitle left and client (bold) and period right, a statement-rule hairline beneath it, then a two-column band with the statement on the left (about 1.35 to 1.5 parts) and the callout, chips and primary download on the right (1 part). Below the band, numbered notes run full width, each a serif heading on a hairline followed by its working table and, where it ties to a statement line, a ruled note total. When a note holds two side-by-side working tables (the ITR slab working, one per regime), each table closes with its own note total inside its column.

Rhythm is set by the sheets and notes: sheets pad 1.25rem by 1.5rem, statement cells 0.62rem by 0.45rem, chips sit 0.45rem apart, each note heading opens 2.3rem below the content above it, and a note total sits 0.1rem under its table with 1.6rem of air before the next note. Note headings carry a 4.5rem scroll margin so a note-reference jump lands below Streamlit's toolbar. Long working tables scroll inside a fixed height of twelve rows.

At 640px and below, the page gutters drop to 1rem with 3.8rem above the header; the header stacks with meta left-aligned; statement padding and type tighten and the Note column narrows to 2.4rem; the approval block becomes a single column; and the note heading count drops to its own line.

## Elevation & Depth

Flat. There are no shadows anywhere. Depth is the contrast of a white sheet on the cool grey ground, edged by a 1px statement-rule border. Interaction depth is shown by colour, not lift: a secondary button's border darkens to navy on hover, a nav item fills with the binding hover tone, and a targeted note heading takes the review tint.

### Named Rules
**The Flat Sheet Rule.** A surface is either ground or a white sheet with a hairline border. Nothing floats, glows or casts a shadow.

## Shapes

Square. Every corner in the system is 2px: buttons, inputs, chips, nav items, alerts, expanders. Sheets themselves are square-edged with a 1px statement-rule border. Lines do the structural work: a 1px navy rule under statement column heads and over subtotals, a 1px navy rule over totals with a 3px double navy rule beneath, row hairlines between lines, and a single muted rule under each blank approval field for a signature.

### Named Rules
**The Ledger Rule.** Deductions are shown in brackets ("(45,643.20)", a dash when nothing is deducted), and so are negative figures in note tables; subtotals are ruled once above; totals are ruled once above and double-ruled below. A note's closing total is ruled the same way so it visibly ties to its statement line.

## Components

### Buttons
Plain and square, navy or white, no ornament.
- **Shape:** gently squared (2px).
- **Primary:** report navy fill, white text. Exactly one per results band: the main download (Download Excel, Excel computation, Download Excel report) or the run action (Reconcile, Compare regimes, Read CAS). Material icon leading.
- **Secondary:** white fill, navy text, statement-rule border, 2.5rem tall; border turns navy on hover. Used for sample downloads, Load sample data, the PDF export and the in-page jump link to a note (Supplier emails).
- **Focus:** a 2px navy outline offset 2px on every focusable element.

### Chips
- **Style:** square (2px) tags with a 1px border, 0.88rem text, the count in bold after the label.
- **Tones:** agreed (green text, green border, green tint), review (ochre text, ochre border, review tint), risk (red text, red border, red tint), neutral (navy text, statement-rule border, white). They sit under the callout figure as the status breakdown.

### Cards / Containers
The only container is the sheet.
- **Corner Style:** square-edged.
- **Background:** sheet white on the cool ground.
- **Shadow Strategy:** none (see Elevation & Depth).
- **Border:** 1px statement rule.
- **Internal Padding:** 1.25rem by 1.5rem for statements, 1.2rem by 1.4rem for callouts, 1rem by 1.2rem for Home contents rows.

### Inputs / Fields
- **Style:** Streamlit widgets with the input-well fill, a statement-rule border and 2px corners.
- **Focus:** the navy focus outline; caret in navy.

### Navigation
- **Style:** the sidebar is the report's navy binding. The brand block comes first: the serif TaxDesk name and a muted caption (tax year, synthetic data notice), closed by a binding-edge hairline. The page list follows below it (the sidebar column is reordered so the brand leads, and Streamlit's own nav separator is hidden). Nav items are 0.95rem in binding text on navy, 2px corners; hover fills with the binding hover tone; the current page fills with the binding active tone in white 600 weight.
- **Mobile:** Streamlit's collapsed sidebar, opened from the top-left control.

### Statement (signature)
A white sheet holding a serif title and a full-width table: Particulars left-aligned, an optional centred Note column, then right-aligned amount columns. Column heads are tracked uppercase labels over a 1px navy rule. Row kinds: plain line; less (bracketed); subtotal (navy rule above, 600); total (navy rule above, 3px double below, 700); risk (label and amount in risk red, weight 600 and 700); memo (muted). A picked column's head and total turn agreed green. Figures follow the Figure Grammar Rule: a statement is set either in paise (GST: 13,00,328.88) or in whole rupees (ITR, MF), and a count column beside the amounts (Invoices) stays whole. On a risk line every value cell, count included, is red. Amounts quoted inside a statement label or a sentence are rewritten as ₹ with Indian grouping ("Rs 75,000" reads "₹75,000").

### Note Reference and Note Heading (signature)
The Note column carries the note number in bold ochre text, no underline until hover, linking to `#note-n`; ranges read "2–3". The matching note heading is "Note n" in serif ochre text beside the note title in serif navy, with an optional muted count pushed right, all on a statement-rule hairline. A heading reached by a jump takes the review tint.

### Callout
The headline beside the statement: a muted caption, the display figure (navy by default, red when money is at risk, green for an agreed result or saving), a muted explanation pointing to the relevant notes, then the status chips.

### Working Table
The table inside a note: a full-width, read-only Streamlit dataframe with a cool-ground header row and table-hairline grid, every float formatted per the Figure Grammar Rule, status words coloured bold in their tone. Long tables scroll inside twelve rows. Columns lead with what the note is about, then the figure that ties, then who it concerns:
- **Invoice notes:** Invoice, then the tying amount (ITC at risk, shortfall, ITC or credit in 2B), then Supplier, then GSTIN, then the remaining detail. Numeric columns that are zero on every row are dropped (IGST on an all-intra-state note). Widths: invoice 165px, supplier 210px, GSTIN 160px.
- **Supplier position:** Status (95px), ITC at risk, Supplier (230px), GSTIN (160px), then the counts.
- **Fund notes:** the amount first (Gain, Total Gain, Cost), then Scheme (300px) and Plan (120px); a "Fund name - Direct Growth" scheme is split into Scheme plus Plan so the fund name never clips.
- **Headers:** plain sentence-case labels with "(₹)" on rupee columns ("ITC at risk (₹)", "Gain (₹)").

### Note Total
A full-width label and amount row ruled with a navy line above and a 3px double navy line below, 600 weight with the amount bold and unbroken, closing a note so its figure ties to the statement line. The amount carries the ₹ sign, in paise by default and in whole rupees where the note works in whole rupees ("Tax on slabs"). Several totals may stack; the second drops its top rule. It sits 0.1rem under the table with 1.6rem below. Every note whose figure ties to a statement line closes with one: each GST invoice note and the supplier position, the MF lot-wise gains, and each ITR slab table.

### Approval Block
Three white cells in a row (Prepared by, Reviewed by, Date) separated by statement-rule lines. Field labels are muted tracked uppercase; the prepared-by value is filled in navy, and the blank fields carry a muted signature rule. Stacks to one column on mobile.

### Alerts
Streamlit alerts restyled as square sheets with a 1px tone border, the tone's tint as fill, navy text, and a 20px stroked SVG icon (1.8px stroke, round caps) in the tone's text colour at the left. Info is neutral, success agreed, warning review, error risk.

## Do's and Don'ts

### Do:
- **Do** open every module with the page header, then the statement and callout side by side, then numbered notes.
- **Do** give every statement line that has working behind it an ochre Note number that links to its `#note-n` heading.
- **Do** bracket deductions, rule subtotals once above, and rule totals once above and double (3px) below, in navy.
- **Do** close a note with a ruled note total when its figure ties to a statement line.
- **Do** format every figure in Indian grouping: paise (2 decimals) where the source tracks paise, whole rupees where the law rounds, no decimals on counts, 4 places on NAV and units.
- **Do** put the ₹ sign on callout figures, note totals and amounts in sentences, and keep table columns plain with "(₹)" in the head.
- **Do** order a note table's columns as subject, tying amount, then who it concerns (Invoice, amount, Supplier, GSTIN; amount, Scheme, Plan), and drop numeric columns that are zero throughout.
- **Do** keep corners at 2px and borders at 1px statement rule.
- **Do** end a results page with the approval block before the footer.

### Don't:
- **Don't** build rows of KPI cards or donut charts; one callout carries the headline figure.
- **Don't** introduce a bright blue accent; navy is ink and binding, not a highlight.
- **Don't** use red for anything except money at risk, or ochre for anything except note references and review items.
- **Don't** add shadows, gradients or lifted cards; depth is white sheet on grey ground.
- **Don't** set table figures, labels or body text in the serif.
- **Don't** put tracked uppercase eyebrow labels above titles or sections.
- **Don't** round corners beyond 2px.
