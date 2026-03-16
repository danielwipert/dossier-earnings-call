/**
 * Chorus AI Systems — Earnings Call Intelligence
 * Report Formatter v2.0 — Magazine-style layout
 *
 * Called by report_formatter.py — not run directly.
 * Usage: node format_report.js <report_json_path> <chart_png_path> <output_docx_path>
 */

const {
  Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell,
  ImageRun, AlignmentType, BorderStyle, WidthType, ShadingType,
  VerticalAlign, PageBreak
} = require('docx');
const fs = require('fs');

// =============================================================================
// DESIGN TOKENS
// =============================================================================
const NAVY        = "1A2E4A";   // deep navy — primary brand
const GOLD        = "C9A84C";   // warm gold — accent
const GOLD_LIGHT  = "FEF9EC";   // gold tint — first takeaway bg
const CHARCOAL    = "1F2937";   // near-black body text
const DARK_GRAY   = "374151";   // secondary text
const MID_GRAY    = "6B7280";   // labels, captions
const LIGHT_BG    = "F3F4F6";   // alternating row bg
const BORDER      = "E5E7EB";   // subtle borders
const GREEN       = "15803D";   // positive signal
const GREEN_BG    = "DCFCE7";   // green card bg
const RED         = "B91C1C";   // negative / watch
const RED_BG      = "FEE2E2";   // red card bg
const AMBER       = "B45309";   // mid-range score
const AMBER_BG    = "FEF3C7";   // amber card bg
const WHITE       = "FFFFFF";
const NAVY_FAINT  = "9CB3D4";   // faint navy for masthead subtext

const CONTENT_WIDTH = 9360;     // DXA — US Letter minus 1" margins

// =============================================================================
// UTILITIES
// =============================================================================

// Strip inline fact citations: [F001], [F001, F002], (F001), (F001, F002)
function stripCitations(text) {
  if (!text) return "";
  return text
    .replace(/\[F\d{3}(?:,\s*F\d{3})*\]/g, "")
    .replace(/\(F\d{3}(?:,\s*F\d{3})*\)/g, "")
    .replace(/[ \t]{2,}/g, " ")   // collapse spaces/tabs only — preserve \n paragraph breaks
    .trim();
}

// Return score background fill based on value
function scoreColor(score) {
  if (score >= 7) return GREEN_BG;
  if (score >= 5) return AMBER_BG;
  return RED_BG;
}

// Return score text color based on value
function scoreTextColor(score) {
  if (score >= 7) return GREEN;
  if (score >= 5) return AMBER;
  return RED;
}

// Visual dot bar: ●●●●●●●●○○ for a score of 8/10
function scoreBar(score) {
  const n = Math.min(10, Math.max(0, Math.round(score)));
  return "\u25CF".repeat(n) + "\u25CB".repeat(10 - n);
}

// Extract the most quotable sentence from a narrative block
// Skips the lead paragraph; prefers sentences with numbers/financial language
function extractPullQuote(narrative, minLen = 90, maxLen = 230) {
  const cleaned = stripCitations(narrative || "").replace(/\*\*/g, "");
  const paras = cleaned.split(/\n\n+/).slice(1); // skip lead para
  const body  = paras.join(" ");
  const sentences = body.match(/[^.!?]+[.!?]+/g) || [];

  let best = null, bestScore = -1;
  sentences.forEach(s => {
    s = s.trim();
    if (s.length < minLen || s.length > maxLen) return;
    let sc = 0;
    if (/\d/.test(s))                              sc += 3;
    if (/\$|%|billion|million/i.test(s))           sc += 2;
    if (/will|expect|target|commit|plan|guid/i.test(s)) sc += 2;
    if (sc > bestScore) { bestScore = sc; best = s; }
  });
  return best;
}

// Render a magazine-style pull quote with decorative quote marks and accent rules
function buildPullQuote(text, accentColor) {
  const clean = text.replace(/^["\u201C\u201D\u201E]+|["\u201C\u201D\u201E]+$/g, "").trim();
  return [
    spacer(6),
    new Paragraph({
      alignment: AlignmentType.CENTER,
      spacing: { before: 120, after: 120, line: 300 },
      indent: { left: 440, right: 440 },
      border: {
        top:    { style: BorderStyle.SINGLE, size: 8, color: accentColor, space: 6 },
        bottom: { style: BorderStyle.SINGLE, size: 8, color: accentColor, space: 6 },
      },
      children: [
        new TextRun({ text: "\u201C", font: "Georgia", size: 44, color: accentColor, bold: true }),
        new TextRun({ text: clean, font: "Georgia", size: 24, italics: true, color: CHARCOAL }),
        new TextRun({ text: "\u201D", font: "Georgia", size: 44, color: accentColor, bold: true }),
      ],
    }),
    spacer(6),
  ];
}

// =============================================================================
// ELEMENT BUILDERS
// =============================================================================

function run(text, opts = {}) {
  return new TextRun({
    text: text || "",
    font: opts.font || "Calibri",
    size: opts.size || 22,
    bold: opts.bold || false,
    italics: opts.italics || false,
    color: opts.color || CHARCOAL,
    break: opts.break || undefined,
  });
}

function para(children, opts = {}) {
  return new Paragraph({
    alignment: opts.align || AlignmentType.LEFT,
    spacing: {
      before: opts.spaceBefore || 0,
      after: opts.spaceAfter !== undefined ? opts.spaceAfter : 100,
      line: opts.lineSpacing || undefined,
    },
    children: Array.isArray(children) ? children : [children],
    border: opts.border || undefined,
    indent: opts.indent || undefined,
  });
}

function spacer(pts = 6) {
  return new Paragraph({
    children: [new TextRun({ text: "", size: pts * 2 })],
    spacing: { before: 0, after: 0 },
  });
}

function divider(color = BORDER, thickness = 8) {
  return new Paragraph({
    children: [new TextRun({ text: "" })],
    border: { bottom: { style: BorderStyle.SINGLE, size: thickness, color, space: 1 } },
    spacing: { before: 80, after: 80 },
  });
}

function cell(children, opts = {}) {
  const none  = { style: BorderStyle.NONE };
  const line  = (c) => ({ style: BorderStyle.SINGLE, size: 2, color: c || opts.borderColor || BORDER });
  const borders = opts.noBorder
    ? { top: none, bottom: none, left: none, right: none }
    : { top: line(), bottom: line(), left: line(), right: line() };

  return new TableCell({
    borders,
    width: opts.width ? { size: opts.width, type: WidthType.DXA } : undefined,
    shading: opts.fill ? { fill: opts.fill, type: ShadingType.CLEAR } : undefined,
    verticalAlign: opts.vAlign || VerticalAlign.CENTER,
    margins: {
      top:    opts.padV  !== undefined ? opts.padV  : 120,
      bottom: opts.padV  !== undefined ? opts.padV  : 120,
      left:   opts.padH  !== undefined ? opts.padH  : 160,
      right:  opts.padH  !== undefined ? opts.padH  : 160,
    },
    columnSpan: opts.span || 1,
    children: Array.isArray(children) ? children : [children],
  });
}

// =============================================================================
// BLOCK: MASTHEAD / COVER BAND
// =============================================================================
function buildHeader(snapshot) {
  const company  = (snapshot.company_name || "").toUpperCase();
  const ticker   = snapshot.ticker  || "";
  const quarter  = snapshot.quarter || "";
  const sector   = snapshot.sector  || "";
  const headline = stripCitations(snapshot.headline || "");

  return [
    // ── Full-bleed navy masthead ──────────────────────────────────────────────
    new Table({
      width: { size: CONTENT_WIDTH, type: WidthType.DXA },
      columnWidths: [CONTENT_WIDTH],
      rows: [new TableRow({ children: [
        cell([
          // Publication label
          para(run("CHORUS AI  ·  EARNINGS CALL INTELLIGENCE", {
            bold: true, size: 16, color: NAVY_FAINT, font: "Arial",
          }), { align: AlignmentType.CENTER, spaceAfter: 100 }),

          // Company name — hero element
          para(run(company, {
            bold: true, size: 72, color: WHITE, font: "Arial",
          }), { align: AlignmentType.CENTER, spaceAfter: 80 }),

          // Internal gold rule
          new Paragraph({
            children: [new TextRun({ text: "" })],
            border: { bottom: { style: BorderStyle.SINGLE, size: 8, color: GOLD, space: 1 } },
            spacing: { before: 0, after: 80 },
          }),

          // Ticker · Quarter · Sector
          para([
            run(ticker, { size: 20, color: NAVY_FAINT, font: "Arial" }),
            run("   ·   ", { size: 20, color: NAVY_FAINT }),
            run(quarter + " Earnings Call", { size: 20, color: NAVY_FAINT, font: "Arial" }),
            ...(sector ? [
              run("   ·   ", { size: 20, color: NAVY_FAINT }),
              run(sector, { size: 20, color: NAVY_FAINT, font: "Arial" }),
            ] : []),
          ], { align: AlignmentType.CENTER, spaceAfter: 80 }),

        ], { fill: NAVY, noBorder: true, padV: 280, padH: 360 }),
      ]})]
    }),

    // Heavy gold rule — the masthead's bottom edge
    new Paragraph({
      children: [new TextRun({ text: "" })],
      border: { bottom: { style: BorderStyle.SINGLE, size: 28, color: GOLD, space: 1 } },
      spacing: { before: 0, after: 0 },
    }),
  ];
}

// =============================================================================
// BLOCK: HEADLINE + DECK COPY + VERIFICATION BADGE
// =============================================================================
function buildHeadline(snapshot, verificationSummary) {
  const headline  = stripCitations(snapshot.headline || "");
  const takeaways = snapshot.key_takeaways || [];
  // Deck copy: first takeaway text, stripped of markdown bold markers
  const deckText  = takeaways.length
    ? stripCitations(takeaways[0].text || "").replace(/\*\*/g, "")
    : "";

  const elements = [];

  // ── Headline — large, editorial ──────────────────────────────────────────
  elements.push(spacer(14));
  elements.push(new Paragraph({
    children: [new TextRun({
      text: headline,
      font: "Georgia",
      size: 38,
      bold: true,
      color: CHARCOAL,
    })],
    spacing: { before: 0, after: 120, line: 360 },
  }));

  // Gold rule under headline
  elements.push(new Paragraph({
    children: [new TextRun({ text: "" })],
    border: { bottom: { style: BorderStyle.SINGLE, size: 8, color: GOLD, space: 1 } },
    spacing: { before: 0, after: 120 },
  }));

  // ── Deck copy — the editorial "why you should care" ────────────────────
  if (deckText) {
    elements.push(new Paragraph({
      children: [new TextRun({
        text: deckText,
        font: "Georgia",
        size: 24,
        italics: true,
        color: DARK_GRAY,
      })],
      spacing: { before: 0, after: 160, line: 320 },
    }));
  }

  // ── Verification badge — single compact line ─────────────────────────
  elements.push(para([
    run("✓ AI-VERIFIED", { size: 16, bold: true, color: GREEN, font: "Arial" }),
    run(
      `   ·   ${verificationSummary.avg_grounding} source grounding` +
      `   ·   ${verificationSummary.contradictions} contradictions detected` +
      `   ·   Model agreement: ${verificationSummary.model_agreement}`,
      { size: 16, color: MID_GRAY, font: "Arial" }
    ),
  ], { spaceAfter: 200 }));

  elements.push(spacer(8));
  return elements;
}

// =============================================================================
// BLOCK: KEY METRICS CARDS
// =============================================================================
function buildMetricCards(snapshot) {
  const financials = (snapshot.key_financials || []).slice(0, 5);
  if (financials.length === 0) return [];

  const elements = [];

  elements.push(
    para(run("BY THE NUMBERS", { bold: true, size: 17, color: MID_GRAY, font: "Arial" }),
         { spaceAfter: 0 })
  );

  const cardW = Math.floor(CONTENT_WIDTH / financials.length);

  // Row 1 — thin colored accent strip (green / red / neutral) at top of each card
  const stripCells = financials.map((m) => {
    const delta = m.yoy_change || "";
    let stripFill = "9CA3AF"; // neutral gray
    if (delta.startsWith("+")) stripFill = GREEN;
    else if (delta.startsWith("-")) stripFill = RED;
    return cell(
      para(run("", { size: 2 })),
      { width: cardW, fill: stripFill, noBorder: true, padV: 20, padH: 0 }
    );
  });

  // Row 2 — card body
  const cardCells = financials.map((m, i) => {
    const value = m.reported_value || "—";
    const label = m.metric_name || "";
    const delta = m.yoy_change || "";
    const vs    = m.vs_estimate || "";

    const shortLabel = label.length > 34 ? label.substring(0, 32) + "…" : label;
    let deltaColor = MID_GRAY;
    if (delta.startsWith("+")) deltaColor = GREEN;
    else if (delta.startsWith("-")) deltaColor = RED;

    const cardFill = i % 2 === 0 ? LIGHT_BG : WHITE;

    return cell([
      para(run(shortLabel, { size: 16, color: MID_GRAY, font: "Arial" }),
           { align: AlignmentType.CENTER, spaceAfter: 50 }),
      para(run(value, { bold: true, size: 52, color: NAVY, font: "Arial" }),
           { align: AlignmentType.CENTER, spaceAfter: 20 }),
      delta
        ? para(run(delta, { bold: true, size: 22, color: deltaColor, font: "Arial" }),
               { align: AlignmentType.CENTER, spaceAfter: 20 })
        : spacer(0),
      vs
        ? para(run(vs, { size: 16, italics: true, color: MID_GRAY }),
               { align: AlignmentType.CENTER, spaceAfter: 0 })
        : spacer(0),
    ], { width: cardW, fill: cardFill, borderColor: BORDER, padV: 200, padH: 80 });
  });

  elements.push(new Table({
    width: { size: CONTENT_WIDTH, type: WidthType.DXA },
    columnWidths: financials.map(() => cardW),
    rows: [
      new TableRow({ children: stripCells }),
      new TableRow({ children: cardCells }),
    ],
  }));

  elements.push(spacer(12));
  return elements;
}

// =============================================================================
// BLOCK: THREE TAKEAWAYS
// =============================================================================
function buildTakeaways(snapshot) {
  const takeaways = (snapshot.key_takeaways || []);
  if (takeaways.length === 0) return [];

  const elements = [];
  elements.push(divider(BORDER, 6));
  elements.push(spacer(4));
  elements.push(
    para(run("THE STORY IN THREE POINTS", { bold: true, size: 22, color: MID_GRAY, font: "Arial" }),
         { spaceAfter: 100 })
  );

  const numW  = 520;
  const textW = CONTENT_WIDTH - numW;

  takeaways.forEach((t, i) => {
    const text = stripCitations(t.text || "");
    const num  = String(t.number || i + 1);

    // Try to split into bold lead sentence + body
    const match = text.match(/^(.*?[.!?])\s+([\s\S]+)$/);
    const lead  = match ? match[1] : text;
    const body  = match ? match[2] : "";

    const cardFill = i === 0 ? GOLD_LIGHT : WHITE;
    const cardBorder = i === 0 ? GOLD : BORDER;

    const numberCell = cell(
      para(run(num, { bold: true, size: 52, color: WHITE, font: "Arial" }),
           { align: AlignmentType.CENTER, spaceAfter: 0 }),
      { width: numW, fill: NAVY, noBorder: true, padV: 180, padH: 80, vAlign: VerticalAlign.CENTER }
    );

    const textContent = [
      para(run(lead, { bold: true, size: 23, color: CHARCOAL, font: "Calibri" }),
           { spaceAfter: body ? 60 : 0 }),
    ];
    if (body) {
      textContent.push(
        para(run(body, { size: 21, color: DARK_GRAY, font: "Calibri" }),
             { spaceAfter: 0 })
      );
    }

    const textCell = cell(textContent, {
      width: textW,
      fill: cardFill,
      borderColor: cardBorder,
      padV: 160, padH: 200,
      vAlign: VerticalAlign.CENTER,
    });

    elements.push(new Table({
      width: { size: CONTENT_WIDTH, type: WidthType.DXA },
      columnWidths: [numW, textW],
      rows: [new TableRow({ children: [numberCell, textCell] })],
    }));
    elements.push(spacer(5));
  });

  elements.push(spacer(8));
  elements.push(divider(BORDER, 6));
  elements.push(spacer(8));
  return elements;
}

// =============================================================================
// BLOCK: SIGNALS AT A GLANCE
// =============================================================================
function buildSignals(sections) {
  const elements = [];

  elements.push(
    para(run("SIGNALS AT A GLANCE", { bold: true, size: 17, color: MID_GRAY, font: "Arial" }),
         { spaceAfter: 80 })
  );

  const greenItems = [];
  const redItems   = [];

  if (sections.S2b) {
    sections.S2b.claims
      .filter(c => c.claim_type === "grounded" || c.claim_type === "derived")
      .slice(0, 4)
      .forEach(c => greenItems.push(stripCitations(c.claim_text)));
  }
  if (sections.S2c) {
    sections.S2c.claims
      .slice(0, 4)
      .forEach(c => redItems.push(stripCitations(c.claim_text)));
  }

  const maxRows = Math.max(greenItems.length, redItems.length, 1);
  const colW = Math.floor(CONTENT_WIDTH / 2);

  const headerRow = new TableRow({ children: [
    cell(
      para(run("  ▲  GREEN FLAGS", { bold: true, size: 21, color: WHITE, font: "Arial" })),
      { width: colW, fill: "166534", noBorder: true, padV: 100 }
    ),
    cell(
      para(run("  ▼  WATCH POINTS", { bold: true, size: 21, color: WHITE, font: "Arial" })),
      { width: colW, fill: "991B1B", noBorder: true, padV: 100 }
    ),
  ]});

  const dataRows = Array.from({ length: maxRows }, (_, i) => {
    const green = greenItems[i] || "";
    const red   = redItems[i]   || "";
    const rowBg = i % 2 === 0;

    return new TableRow({ children: [
      cell(
        green
          ? para([run("  ", { size: 20 }), run(green, { size: 20, color: CHARCOAL })], { spaceAfter: 0 })
          : para(run("", { size: 20 }), { spaceAfter: 0 }),
        { width: colW, fill: rowBg ? GREEN_BG : WHITE, borderColor: BORDER, padV: 100 }
      ),
      cell(
        red
          ? para([run("  ", { size: 20 }), run(red, { size: 20, color: CHARCOAL })], { spaceAfter: 0 })
          : para(run("", { size: 20 }), { spaceAfter: 0 }),
        { width: colW, fill: rowBg ? RED_BG : WHITE, borderColor: BORDER, padV: 100 }
      ),
    ]});
  });

  elements.push(new Table({
    width: { size: CONTENT_WIDTH, type: WidthType.DXA },
    columnWidths: [colW, colW],
    rows: [headerRow, ...dataRows],
  }));

  elements.push(spacer(4));
  return elements;
}

// =============================================================================
// BLOCK: SCORECARD (radar chart + color-coded score table)
// =============================================================================
function buildScorecard(radarScores, chartPngPath) {
  const elements = [];

  elements.push(new Paragraph({ children: [new PageBreak()], spacing: { before: 0, after: 0 } }));
  elements.push(spacer(4));
  elements.push(
    para(run("EARNINGS CALL RADAR", { bold: true, size: 17, color: MID_GRAY, font: "Arial" }),
         { spaceAfter: 80 })
  );

  // Radar chart
  try {
    const imageBuffer = fs.readFileSync(chartPngPath);
    elements.push(new Paragraph({
      alignment: AlignmentType.CENTER,
      spacing: { before: 0, after: 160 },
      children: [new ImageRun({
        data: imageBuffer,
        transformation: { width: 380, height: 380 },
        type: "png",
      })],
    }));
  } catch {
    elements.push(para(run("[Radar chart unavailable]", { italics: true, color: MID_GRAY })));
  }

  if (radarScores && radarScores.dimension_scores) {
    const DISPLAY_NAMES = {
      revenue_momentum:    "Revenue Momentum",
      margin_health:       "Margin Health",
      guidance_confidence: "Guidance Confidence",
      mgmt_transparency:   "Mgmt Transparency",
      strategic_clarity:   "Strategic Clarity",
      earnings_quality:    "Earnings Quality",
      forward_visibility:  "Forward Visibility",
    };

    const labelW = 2400;
    const scoreW = 720;
    const noteW  = CONTENT_WIDTH - labelW - scoreW;

    const headerRow = new TableRow({ children: [
      cell(para(run("DIMENSION", { bold: true, size: 18, color: WHITE, font: "Arial" })),
           { width: labelW, fill: NAVY, noBorder: true }),
      cell(para(run("SCORE", { bold: true, size: 18, color: WHITE, font: "Arial" }),
               { align: AlignmentType.CENTER }),
           { width: scoreW, fill: NAVY, noBorder: true }),
      cell(para(run("RATIONALE", { bold: true, size: 18, color: WHITE, font: "Arial" })),
           { width: noteW, fill: NAVY, noBorder: true }),
    ]});

    const DIMENSION_FALLBACK_RATIONALE = {
      revenue_momentum:    "Score reflects the revenue growth rate and performance relative to expectations for the quarter.",
      margin_health:       "Score reflects operating margin direction and capital expenditure trajectory observed this quarter.",
      guidance_confidence: "Score reflects the number and specificity of forward-looking commitments made by management.",
      mgmt_transparency:   "Score reflects management's directness in Q&A and the completeness of disclosures relative to analyst questions asked.",
      strategic_clarity:   "Score reflects the coherence between management's stated priorities and observable capital allocation decisions.",
      earnings_quality:    "Score reflects the proportion of recurring versus one-time items contributing to reported results.",
      forward_visibility:  "Score reflects the quantity and precision of quantitative forward guidance provided across revenue, margins, and capital expenditure.",
    };

    const dataRows = radarScores.dimension_scores.map((d, i) => {
      const name      = DISPLAY_NAMES[d.dimension] || d.dimension;
      const score     = d.published_score;
      const rawRationale = (d.scoring_rationale || "").trim();
      const rationale = (rawRationale.length > 8 ? rawRationale : (DIMENSION_FALLBACK_RATIONALE[d.dimension] || "Score reflects analysis of this dimension against the quarter's available evidence.")).substring(0, 200);
      const rowFill   = i % 2 === 0 ? WHITE : LIGHT_BG;
      const tc        = scoreTextColor(score);

      return new TableRow({ children: [
        cell(para(run(name, { bold: true, size: 21, font: "Calibri" })),
             { width: labelW, fill: rowFill, borderColor: BORDER }),
        cell([
          para(run(String(score), { bold: true, size: 34, color: tc, font: "Arial" }),
               { align: AlignmentType.CENTER, spaceAfter: 20 }),
          para(run(scoreBar(score), { size: 14, color: tc, font: "Arial" }),
               { align: AlignmentType.CENTER, spaceAfter: 0 }),
        ], { width: scoreW, fill: scoreColor(score), borderColor: BORDER }),
        cell(para(run(rationale, { size: 19, italics: true, color: DARK_GRAY })),
             { width: noteW, fill: rowFill, borderColor: BORDER }),
      ]});
    });

    elements.push(new Table({
      width: { size: CONTENT_WIDTH, type: WidthType.DXA },
      columnWidths: [labelW, scoreW, noteW],
      rows: [headerRow, ...dataRows],
    }));
  }

  elements.push(spacer(12));
  return elements;
}

// =============================================================================
// S2a TWO-COLUMN LAYOUT
// Groups the S2a narrative into subheading+body blocks and renders them
// in a 2-column magazine grid. Numbers are bolded inline so they pop.
// =============================================================================
function renderS2aColumns(elements, processedParas, accent, accentBg, pullQuoteText) {
  // ---- Group paragraphs into {heading, paras[]} blocks ----
  const blocks = [];
  let curr = { heading: null, paras: [] };

  processedParas.forEach(p => {
    const hm = p.match(/^\*\*([^*]+)\*\*\s*$/);
    if (hm) {
      if (curr.heading !== null || curr.paras.length > 0) blocks.push(curr);
      curr = { heading: hm[1], paras: [] };
    } else {
      curr.paras.push(p);
    }
  });
  if (curr.heading !== null || curr.paras.length > 0) blocks.push(curr);

  // ---- Intro block → full-width lead paragraph ----
  const introBlock = blocks[0] || { heading: null, paras: [] };
  if (introBlock.paras.length > 0) {
    const p    = introBlock.paras[0];
    const clean = p.replace(/\*\*/g, "");
    const m    = clean.match(/^(.*?[.!?])\s*([\s\S]*)$/);
    const lead = m ? m[1] : clean;
    const rest = m ? m[2] : "";
    elements.push(new Paragraph({
      children: [
        new TextRun({ text: lead, font: "Georgia", size: 27, bold: true, color: NAVY }),
        ...(rest ? [new TextRun({ text: "  " + rest, font: "Georgia", size: 24, color: DARK_GRAY })] : []),
      ],
      spacing: { before: 80, after: 220, line: 340 },
      indent: { left: 480, right: 280 },
      border: { left: { style: BorderStyle.SINGLE, size: 34, color: accent, space: 14 } },
    }));
  }

  // Pull quote after intro
  if (pullQuoteText) {
    buildPullQuote(pullQuoteText, accent).forEach(el => elements.push(el));
  }

  // ---- Content blocks → 2-column grid ----
  const contentBlocks = blocks.slice(1);
  const colW = Math.floor(CONTENT_WIDTH / 2);

  // Convert one block into an array of docx Paragraph objects
  function blockToDocx(block) {
    const out = [];

    // Subheading: bold text with accent underline rule
    if (block.heading) {
      out.push(new Paragraph({
        children: [new TextRun({
          text: block.heading.toUpperCase(),
          font: "Arial", size: 19, bold: true, color: NAVY,
        })],
        spacing: { before: 60, after: 100 },
        border: { bottom: { style: BorderStyle.SINGLE, size: 8, color: accent, space: 4 } },
      }));
    }

    // Body: render each paragraph whole, bolding numbers/stats inline
    block.paras.forEach(p => {
      const parts = p.replace(/\*\*/g, "").split(/(\d+\.?\d*%|\$[\d.,]+(?:\s*(?:billion|million|B|M))?)/gi);
      const runs  = parts.map(part => {
        const isStat = /\d+\.?\d*%|\$[\d.,]+/.test(part);
        return new TextRun({
          text:  part,
          font:  isStat ? "Arial" : "Calibri",
          size:  isStat ? 22 : 21,
          bold:  isStat,
          color: isStat ? NAVY : CHARCOAL,
        });
      });
      out.push(new Paragraph({
        children: runs,
        spacing: { before: 0, after: 120, line: 290 },
      }));
    });

    return out;
  }

  // Render content blocks in pairs side-by-side
  for (let i = 0; i < contentBlocks.length; i += 2) {
    const leftDocx  = blockToDocx(contentBlocks[i]);
    const rightDocx = contentBlocks[i + 1]
      ? blockToDocx(contentBlocks[i + 1])
      : [new Paragraph({ children: [new TextRun({ text: "" })] })];

    elements.push(spacer(4));
    elements.push(new Table({
      width: { size: CONTENT_WIDTH, type: WidthType.DXA },
      columnWidths: [colW, colW],
      rows: [new TableRow({ children: [
        cell(leftDocx,  { width: colW, noBorder: true, padV: 80, padH: 180, vAlign: VerticalAlign.TOP }),
        cell(rightDocx, { width: colW, noBorder: true, padV: 80, padH: 180, vAlign: VerticalAlign.TOP }),
      ]})],
    }));
  }

  elements.push(spacer(8));
}

// =============================================================================
// BLOCK: NARRATIVE DEEP DIVE
// =============================================================================
function buildNarrative(sections) {
  const elements = [];

  const SECTION_META = [
    {
      id: "S2a",
      label: "THE QUARTER IN CONTEXT",
      number: "01",
      accent: GOLD,
      accentBg: GOLD_LIGHT,
      fill: NAVY,
      subtitleColor: NAVY_FAINT,
      subtitle: "Performance & results breakdown",
    },
    {
      id: "S2b",
      label: "WHAT MANAGEMENT IS SIGNALING",
      number: "02",
      accent: "3B82F6",
      accentBg: "EFF6FF",
      fill: "1E3A6E",
      subtitleColor: "93C5FD",
      subtitle: "Reading the strategic intent",
    },
    {
      id: "S2c",
      label: "WHAT WASN'T SAID",
      number: "03",
      accent: AMBER,
      accentBg: AMBER_BG,
      fill: CHARCOAL,
      subtitleColor: "D1D5DB",
      subtitle: "Omissions, evasions & the silences that matter",
    },
    {
      id: "S2d",
      label: "THE BIGGER PICTURE",
      number: "04",
      accent: "059669",
      accentBg: "ECFDF5",
      fill: "064E3B",
      subtitleColor: "6EE7B7",
      subtitle: "Context, implications & what to watch",
    },
  ];

  SECTION_META.forEach(({ id, label, number, accent, accentBg, fill, subtitleColor, subtitle }) => {
    elements.push(spacer(8));

    // ---- MAGAZINE-STYLE SECTION HEADER: number block + title panel ----
    const numBlockW = 860;
    const titleBlockW = CONTENT_WIDTH - numBlockW;
    elements.push(new Table({
      width: { size: CONTENT_WIDTH, type: WidthType.DXA },
      columnWidths: [numBlockW, titleBlockW],
      rows: [new TableRow({ children: [
        // Large section number in accent color
        cell(
          para(run(number, { bold: true, size: 52, color: WHITE, font: "Arial" }),
               { align: AlignmentType.CENTER, spaceAfter: 0 }),
          { width: numBlockW, fill: accent, noBorder: true, padV: 180, padH: 60, vAlign: VerticalAlign.CENTER }
        ),
        // Section title + subtitle on dark fill
        cell([
          para(run(label, { bold: true, size: 22, color: WHITE, font: "Arial" }),
               { spaceAfter: 60 }),
          para(run(subtitle, { size: 18, italics: true, color: subtitleColor, font: "Calibri" }),
               { spaceAfter: 0 }),
        ], { width: titleBlockW, fill, noBorder: true, padV: 150, padH: 220, vAlign: VerticalAlign.CENTER }),
      ]})]
    }));

    const section = sections[id];
    if (!section) {
      elements.push(spacer(6));
      elements.push(para(run(
        "[This section was omitted — verification could not be completed after maximum retries.]",
        { italics: true, size: 20, color: MID_GRAY }
      ), { spaceBefore: 80, spaceAfter: 160 }));
      return;
    }

    elements.push(spacer(4));

    // ---- Parse narrative: separate "to watch" list for S2d ----
    const narrative = stripCitations(section.narrative || "");
    const rawParas = narrative.split(/\n\n+/);
    let isFirst = true;
    let bodyParaCount = 0;
    let pullQuoteInserted = false;
    const pullQuoteText = extractPullQuote(section.narrative || "");
    let watchListItems = [];
    const processedParas = [];

    rawParas.forEach(p => {
      p = p.trim();
      if (!p) return;

      // Detect "To monitor in the next quarter" paragraph in S2d
      if (id === "S2d" && /to monitor/i.test(p)) {
        // Strip the intro text, then try to split on numbered items
        const listPart = p.replace(/^.*?(?:to monitor[^:]*:?\s*)/i, "");
        const byNewline = listPart.split(/\n/).map(l => l.replace(/^\d+\.\s*/, "").trim()).filter(Boolean);
        if (byNewline.length > 1) {
          watchListItems = byNewline;
        } else {
          const byComma = listPart.split(/,\s*(?=\d+\.)/).map(l => l.replace(/^\d+\.\s*/, "").trim()).filter(Boolean);
          watchListItems = byComma.length > 1 ? byComma : byNewline.length ? byNewline : [listPart];
        }
        return; // Rendered separately below as a watchlist box
      }

      processedParas.push(p);
    });

    // ---- Render paragraphs ----
    if (id === "S2a") {
      renderS2aColumns(elements, processedParas, accent, accentBg, pullQuoteText);
    } else { processedParas.forEach(p => {
      // Standalone subheading: entire paragraph is **text**
      // Rendered as a two-column band: thick accent stripe left + tinted heading panel
      const subheadMatch = p.match(/^\*\*([^*]+)\*\*\s*$/);
      if (subheadMatch) {
        elements.push(spacer(8));
        const stripeW = 60;
        const headW   = CONTENT_WIDTH - stripeW;
        elements.push(new Table({
          width: { size: CONTENT_WIDTH, type: WidthType.DXA },
          columnWidths: [stripeW, headW],
          rows: [new TableRow({ children: [
            cell(para(run("", { size: 2 })),
                 { width: stripeW, fill: accent, noBorder: true, padV: 80, padH: 0 }),
            cell(
              para(run(subheadMatch[1].toUpperCase(), { bold: true, size: 20, color: NAVY, font: "Arial" }),
                   { spaceAfter: 0 }),
              { width: headW, fill: accentBg, noBorder: true, padV: 110, padH: 200 }
            ),
          ]})]
        }));
        elements.push(spacer(4));
        return;
      }

      // First paragraph → larger deck/lede copy with section accent
      if (isFirst) {
        isFirst = false;
        const cleanText = p.replace(/\*\*/g, "");
        const firstSentMatch = cleanText.match(/^(.*?[.!?])\s*([\s\S]*)$/);
        const leadSentence = firstSentMatch ? firstSentMatch[1] : cleanText;
        const rest = firstSentMatch ? firstSentMatch[2] : "";

        const leadRuns = [
          new TextRun({ text: leadSentence, font: "Georgia", size: 27, bold: true, color: NAVY }),
        ];
        if (rest) {
          leadRuns.push(new TextRun({ text: "  " + rest, font: "Georgia", size: 24, color: DARK_GRAY }));
        }

        elements.push(new Paragraph({
          children: leadRuns,
          spacing: { before: 80, after: 220, line: 340 },
          indent: { left: 480, right: 280 },
          border: {
            left: { style: BorderStyle.SINGLE, size: 34, color: accent, space: 14 },
          },
        }));
        return;
      }

      // Blockquote: lines starting with ">"
      if (p.startsWith(">")) {
        elements.push(new Paragraph({
          children: [new TextRun({
            text: p.replace(/^>\s*/, "").replace(/\*\*/g, ""),
            font: "Georgia",
            size: 21,
            italics: true,
            color: MID_GRAY,
          })],
          spacing: { before: 120, after: 120 },
          indent: { left: 720, right: 360 },
          border: { left: { style: BorderStyle.SINGLE, size: 12, color: BORDER, space: 8 } },
        }));
        return;
      }

      // Data-dense paragraph: 3+ stat figures → sentence-per-row shaded panel
      // Numbers appear bold in navy so they jump off the page
      const statHits = (p.match(/\d+\.?\d*%|\$[\d.,]+\s*(?:billion|million|B|M)?/gi) || []).length;
      const sentences = (p.match(/[^.!?]+[.!?]+/g) || []).map(s => s.trim()).filter(Boolean);
      if (statHits >= 3 && sentences.length >= 2) {
        elements.push(new Table({
          width: { size: CONTENT_WIDTH, type: WidthType.DXA },
          columnWidths: [CONTENT_WIDTH],
          rows: sentences.map((sentence, idx) => {
            const sentParts = sentence.split(/(\d+\.?\d*%|\$[\d.,]+(?:\s*(?:billion|million|B|M))?)/gi);
            const sentRuns = sentParts.map(part => {
              const isStat = /\d+\.?\d*%|\$[\d.,]+/.test(part);
              return new TextRun({
                text: part,
                font: isStat ? "Arial" : "Calibri",
                size: isStat ? 22 : 21,
                bold: isStat,
                color: isStat ? NAVY : CHARCOAL,
              });
            });
            return new TableRow({ children: [
              cell(
                new Paragraph({ children: sentRuns, spacing: { before: 0, after: 0 } }),
                { fill: idx % 2 === 0 ? accentBg : WHITE, noBorder: false, borderColor: BORDER, padV: 100, padH: 200 }
              ),
            ]});
          }),
        }));
        elements.push(spacer(6));
        bodyParaCount++;
        if (!pullQuoteInserted && bodyParaCount === 2 && pullQuoteText) {
          pullQuoteInserted = true;
          buildPullQuote(pullQuoteText, accent).forEach(el => elements.push(el));
        }
        return;
      }

      // Normal paragraph — parse inline **bold**
      const parts = p.split(/(\*\*[^*]+\*\*)/g);
      const runs = parts.map(part => {
        if (part.startsWith("**") && part.endsWith("**")) {
          return new TextRun({ text: part.replace(/\*\*/g, ""), font: "Calibri", size: 22, bold: true, color: CHARCOAL });
        }
        return new TextRun({ text: part, font: "Calibri", size: 22, color: CHARCOAL });
      });

      elements.push(new Paragraph({
        children: runs,
        spacing: { before: 0, after: 170, line: 300 },
      }));

      bodyParaCount++;

      // Insert pull quote after 2nd body paragraph
      if (!pullQuoteInserted && bodyParaCount === 2 && pullQuoteText) {
        pullQuoteInserted = true;
        buildPullQuote(pullQuoteText, accent).forEach(el => elements.push(el));
      }
    }); } // end else (non-S2a rendering)

    // ---- S2b: KEY SIGNALS panel (pulled from structured claims) ----
    if (id === "S2b" && section.claims && section.claims.length > 0) {
      // Skip the first claim if it's just a repetition of top-line numbers (usually the first grounded claim)
      const signals = section.claims.slice(1).filter(c =>
        c.claim_type === "grounded" || c.claim_type === "interpretive"
      ).slice(0, 4);

      if (signals.length > 0) {
        elements.push(spacer(10));
        elements.push(new Table({
          width: { size: CONTENT_WIDTH, type: WidthType.DXA },
          columnWidths: [CONTENT_WIDTH],
          rows: [
            new TableRow({ children: [
              cell(
                para(run("KEY SIGNALS FROM MANAGEMENT", { bold: true, size: 19, color: WHITE, font: "Arial" })),
                { fill: accent, noBorder: true, padV: 100, padH: 200 }
              ),
            ]}),
            ...signals.map((sig, i) => new TableRow({ children: [
              cell([
                para([
                  run("→  ", { bold: true, size: 21, color: accent }),
                  run(stripCitations(sig.claim_text), { size: 21, color: CHARCOAL }),
                ], { spaceAfter: 0 }),
              ], { fill: i % 2 === 0 ? accentBg : WHITE, noBorder: false, borderColor: BORDER, padV: 110, padH: 200 }),
            ]})),
          ],
        }));
        elements.push(spacer(8));
      }
    }

    // ---- S2c: NOTABLE OMISSIONS panel (interpretive claims with no source grounding) ----
    if (id === "S2c" && section.claims && section.claims.length > 0) {
      const omissions = section.claims.filter(c =>
        c.claim_type === "interpretive" || !c.source_fact_ids || c.source_fact_ids.length === 0
      ).slice(0, 5);

      if (omissions.length > 0) {
        elements.push(spacer(10));
        elements.push(new Table({
          width: { size: CONTENT_WIDTH, type: WidthType.DXA },
          columnWidths: [CONTENT_WIDTH],
          rows: [
            new TableRow({ children: [
              cell(
                para(run("NOTABLE OMISSIONS & EVASIONS", { bold: true, size: 19, color: WHITE, font: "Arial" })),
                { fill: CHARCOAL, noBorder: true, padV: 100, padH: 200 }
              ),
            ]}),
            ...omissions.map((o, i) => new TableRow({ children: [
              cell([
                para([
                  run("◦  ", { bold: true, size: 22, color: accent }),
                  run(stripCitations(o.claim_text), { size: 21, italics: true, color: DARK_GRAY }),
                ], { spaceAfter: 0 }),
              ], { fill: i % 2 === 0 ? accentBg : WHITE, noBorder: false, borderColor: BORDER, padV: 110, padH: 200 }),
            ]})),
          ],
        }));
        elements.push(spacer(8));
      }
    }

    // ---- S2d: WHAT TO WATCH checklist ----
    if (id === "S2d" && watchListItems.length > 0) {
      elements.push(spacer(10));
      elements.push(new Table({
        width: { size: CONTENT_WIDTH, type: WidthType.DXA },
        columnWidths: [CONTENT_WIDTH],
        rows: [
          new TableRow({ children: [
            cell(
              para(run("WHAT TO WATCH NEXT QUARTER", { bold: true, size: 19, color: WHITE, font: "Arial" })),
              { fill: accent, noBorder: true, padV: 100, padH: 200 }
            ),
          ]}),
          ...watchListItems.map((item, i) => {
            const cleanItem = item.replace(/\.$/, "").trim();
            return new TableRow({ children: [
              cell([
                para([
                  run(`${i + 1}`, { bold: true, size: 26, color: accent, font: "Arial" }),
                  run("   " + cleanItem, { size: 21, color: CHARCOAL }),
                ], { spaceAfter: 0 }),
              ], { fill: i % 2 === 0 ? accentBg : WHITE, noBorder: false, borderColor: BORDER, padV: 120, padH: 200 }),
            ]});
          }),
        ],
      }));
      elements.push(spacer(2));
    }

    elements.push(spacer(2));
  });

  return elements;
}

// =============================================================================
// BLOCK: VERIFICATION APPENDIX
// =============================================================================
function buildVerification(verification, radarScores) {
  const elements = [];

  elements.push(divider(BORDER, 6));
  elements.push(spacer(4));

  elements.push(new Table({
    width: { size: CONTENT_WIDTH, type: WidthType.DXA },
    columnWidths: [CONTENT_WIDTH],
    rows: [new TableRow({ children: [
      cell(
        para(run("VERIFICATION REPORT", { bold: true, size: 20, color: WHITE, font: "Arial" })),
        { fill: CHARCOAL, noBorder: true, padV: 120, padH: 200 }
      ),
    ]})]
  }));

  elements.push(spacer(6));
  elements.push(para(run(
    "Every factual claim in this report was independently verified against the source transcript " +
    "by a separate AI model. This appendix documents the verification process and its findings.",
    { size: 20, italics: true, color: MID_GRAY }
  ), { spaceAfter: 160 }));

  // Grounding scores by section
  if (verification && verification.source_grounding_scores) {
    elements.push(para(run("Source Grounding by Section", { bold: true, size: 22, color: CHARCOAL }),
                       { spaceAfter: 80 }));
    const entries = Object.entries(verification.source_grounding_scores);
    const colW = Math.floor(CONTENT_WIDTH / Math.max(entries.length, 1));

    elements.push(new Table({
      width: { size: CONTENT_WIDTH, type: WidthType.DXA },
      columnWidths: entries.map(() => colW),
      rows: [
        new TableRow({ children: entries.map(([sec]) =>
          cell(para(run(sec, { bold: true, size: 20, color: WHITE, font: "Arial" }),
                    { align: AlignmentType.CENTER }),
               { width: colW, fill: NAVY, noBorder: true })
        )}),
        new TableRow({ children: entries.map(([, score]) =>
          cell(para(run(`${(score * 100).toFixed(0)}%`, { bold: true, size: 30, color: GREEN }),
                    { align: AlignmentType.CENTER }),
               { width: colW })
        )}),
      ],
    }));
    elements.push(spacer(12));
  }

  // Contradiction count
  const totalContradictions = Object.values((verification || {}).contradiction_counts || {})
    .reduce((a, b) => a + b, 0);
  elements.push(para([
    run("Contradiction Check: ", { bold: true, size: 22 }),
    run(
      totalContradictions === 0
        ? "✓ 0 contradictions detected"
        : `✗ ${totalContradictions} contradictions found`,
      { size: 22, color: totalContradictions === 0 ? GREEN : RED }
    ),
  ], { spaceAfter: 120 }));

  // Scoring disagreements
  if (radarScores && radarScores.dimension_scores) {
    const disagreements = radarScores.dimension_scores.filter(d => !d.models_agreed);
    if (disagreements.length > 0) {
      elements.push(para(run("Scoring Disagreements", { bold: true, size: 22, color: CHARCOAL }),
                         { spaceBefore: 120, spaceAfter: 80 }));
      disagreements.forEach(d => {
        elements.push(para(run(`• ${d.dimension}: ${d.disagreement_note || ""}`,
                               { size: 20, italics: true }),
                           { spaceAfter: 80 }));
      });
    }
  }

  // S5 advisory flags
  const s5 = (verification || {}).s5_issues || {};
  const allFlags = [
    ...(s5.cross_section_issues || []),
    ...(s5.labeling_issues || []),
    ...(s5.framing_concerns || []),
  ];
  if (allFlags.length > 0) {
    elements.push(para(run("Advisory Flags", { bold: true, size: 22, color: CHARCOAL }),
                       { spaceBefore: 120, spaceAfter: 80 }));
    allFlags.forEach(issue => {
      const text = issue.issue_description || issue.concern_description || JSON.stringify(issue);
      elements.push(para(run(`• ${text}`, { size: 20, italics: true }), { spaceAfter: 80 }));
    });
  }

  // Verification limitations (always shown — Principle 13)
  if (verification && verification.verification_limitations) {
    elements.push(para(run("Verification Limitations", { bold: true, size: 22, color: CHARCOAL }),
                       { spaceBefore: 160, spaceAfter: 80 }));
    elements.push(para(run(verification.verification_limitations,
                            { size: 19, italics: true, color: MID_GRAY }),
                       { spaceAfter: 120 }));
  }

  elements.push(spacer(16));
  elements.push(divider(BORDER, 6));
  elements.push(para(
    run("Produced by Chorus AI Systems  ·  Multi-model verification pipeline with source grounding",
        { size: 17, italics: true, color: MID_GRAY }),
    { align: AlignmentType.CENTER, spaceBefore: 120 }
  ));

  return elements;
}

// =============================================================================
// MAIN
// =============================================================================
async function main() {
  const args = process.argv.slice(2);
  if (args.length < 3) {
    console.error("Usage: node format_report.js <report_json> <chart_png> <output_docx>");
    process.exit(1);
  }

  const [reportJsonPath, chartPngPath, outputDocxPath] = args;
  const reportData = JSON.parse(fs.readFileSync(reportJsonPath, 'utf8'));
  const { snapshot, sections, radar_scores, verification } = reportData;

  // Build verification summary for header badge
  const groundingVals = verification && verification.source_grounding_scores
    ? Object.values(verification.source_grounding_scores) : [];
  const avgGrounding = groundingVals.length
    ? groundingVals.reduce((a, b) => a + b, 0) / groundingVals.length : null;

  const verificationSummary = {
    avg_grounding: avgGrounding ? `${(avgGrounding * 100).toFixed(0)}%` : "—",
    contradictions: verification
      ? Object.values(verification.contradiction_counts || {}).reduce((a, b) => a + b, 0) : "—",
    model_agreement: (radar_scores && radar_scores.dimension_scores &&
      radar_scores.dimension_scores.every(d => d.models_agreed)) ? "High" : "Partial",
  };

  const children = [
    ...buildHeader(snapshot),
    ...buildHeadline(snapshot, verificationSummary),
    ...buildMetricCards(snapshot),
    ...buildSignals(sections),
    ...buildTakeaways(snapshot),
    ...buildScorecard(radar_scores, chartPngPath),
    ...buildNarrative(sections),
    ...buildVerification(verification, radar_scores),
  ];

  const doc = new Document({
    styles: {
      default: {
        document: { run: { font: "Calibri", size: 22 } },
      },
    },
    sections: [{
      properties: {
        page: {
          size: { width: 12240, height: 15840 },
          margin: { top: 1080, right: 1080, bottom: 1080, left: 1080 },
        },
      },
      children,
    }],
  });

  const buffer = await Packer.toBuffer(doc);
  fs.writeFileSync(outputDocxPath, buffer);
  console.log(`Report saved: ${outputDocxPath}`);
}

main().catch(err => { console.error(err); process.exit(1); });
