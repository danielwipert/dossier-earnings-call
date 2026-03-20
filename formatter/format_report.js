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

const CONTENT_WIDTH = 9640;     // DXA — US Letter (12240) minus 0.9" left+right margins (1300+1300)

// =============================================================================
// UTILITIES
// =============================================================================

// Strip inline citations and any bracketed model annotations
function stripCitations(text) {
  if (!text) return "";
  return text
    .replace(/\[F[^\]]*\]/g, "")                     // [F001], [F020 is not available...], etc.
    .replace(/\(F\d{3}(?:,\s*F\d{3})*\)/g, "")      // (F001), (F001, F002)
    .replace(/\(Fact ID:[^)]*\)/gi, "")               // (Fact ID: F004, F006)
    .replace(/\[Context:[^\]]*\]/gi, "")              // [Context: Prior Quarter Commitments]
    .replace(/[ \t]{2,}/g, " ")                      // collapse extra spaces/tabs
    .replace(/\s+([,;.])/g, "$1")                    // remove space before punctuation
    .trim();
}

// Format a raw pipeline metric value for compact card display.
// e.g. "$1,989 million" → "$1.99B", "> $6 billion" → ">$6B", "4.8 million" → "4.8M"
function formatDisplayValue(raw) {
  if (!raw) return "—";
  const s = String(raw).trim();

  // "> $X billion/million" patterns
  const gtBillionMatch = s.match(/^>\s*\$?([\d,]+\.?\d*)\s*billion/i);
  if (gtBillionMatch) return `> $${parseFloat(gtBillionMatch[1].replace(/,/g, '')).toFixed(0)}B`;
  const gtMillionMatch = s.match(/^>\s*\$?([\d,]+\.?\d*)\s*million/i);
  if (gtMillionMatch) {
    const n = parseFloat(gtMillionMatch[1].replace(/,/g, ''));
    return n >= 1000 ? `> $${(n/1000).toFixed(1)}B` : `> $${Math.round(n)}M`;
  }

  // "$X billion" or "$X.Y billion"
  const billionMatch = s.match(/^\$?([\d,]+\.?\d*)\s*billion/i);
  if (billionMatch) return `$${parseFloat(billionMatch[1].replace(/,/g, '')).toFixed(1)}B`;

  // "$X million" or "$X.Y million"
  const millionMatch = s.match(/^\$?([\d,]+\.?\d*)\s*million/i);
  if (millionMatch) {
    const n = parseFloat(millionMatch[1].replace(/,/g, ''));
    if (n >= 1000) return `$${(n/1000).toFixed(2)}B`;
    // Round to nearest integer, unless it has meaningful decimal
    return `$${n % 1 === 0 ? n : n.toFixed(0)}M`;
  }

  // "X million" (no dollar sign — e.g. MUPs)
  const plainMillionMatch = s.match(/^([\d,]+\.?\d*)\s*million/i);
  if (plainMillionMatch) {
    const n = parseFloat(plainMillionMatch[1].replace(/,/g, ''));
    return `${n % 1 === 0 ? n : n.toFixed(1)}M`;
  }

  // Already short (under 10 chars) — return as-is
  if (s.length <= 12) return s;

  return s;
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
function extractPullQuote(narrative, minLen = 90, maxLen = 400) {
  const cleaned = stripCitations(narrative || "").replace(/\*\*/g, "");
  const paras = cleaned.split(/\n+/).slice(1); // skip lead para
  const body  = paras.join(" ");
  // Protect decimal points (e.g. $6.5, 43.2%) so they don't split sentences
  const protected_ = body.replace(/(\d)\.(\d)/g, "$1\x01$2");
  const rawSentences = protected_.match(/[^.!?]+[.!?]+/g) || [];
  const sentences = rawSentences.map(s => s.replace(/\x01/g, ".").trim());

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

// Break a long paragraph (>600 chars) into smaller ones at sentence boundaries.
// Prevents walls of text when the LLM returns dense single-paragraph blocks.
function breakLongParagraph(text, maxChars = 600) {
  if (text.length <= maxChars) return [text];

  // Protect decimal numbers so they don't get split at the period
  const protected_ = text.replace(/(\d)\.(\d)/g, "$1\x01$2");
  const sentences = protected_.match(/[^.!?]+[.!?]+[\s"]*/g) || [text];
  const restored = sentences.map(s => s.replace(/\x01/g, ".").trim()).filter(Boolean);

  const chunks = [];
  let current = "";
  for (const s of restored) {
    if (current.length + s.length > maxChars && current.length > 0) {
      chunks.push(current.trim());
      current = s;
    } else {
      current += (current ? " " : "") + s;
    }
  }
  if (current.trim()) chunks.push(current.trim());
  return chunks.length ? chunks : [text];
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
    keepNext: opts.keepNext || false,
    keepLines: opts.keepLines || false,
  });
}

// pts = visual gap in points. Uses spacing.after for reliable PDF rendering.
function spacer(pts = 8, keepNext = false) {
  return new Paragraph({
    children: [new TextRun({ text: "", size: 4 })],   // 2pt invisible anchor
    spacing: { before: 0, after: pts * 20 },          // after in twentieths of a point
    keepNext,
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

  // Format a publication date string: e.g. "17 March 2026"
  const now = new Date();
  const dateStr = now.toLocaleDateString("en-GB", { day: "numeric", month: "long", year: "numeric" });

  return [
    // ── Full-bleed navy masthead ──────────────────────────────────────────────
    new Table({
      width: { size: CONTENT_WIDTH, type: WidthType.DXA },
      columnWidths: [CONTENT_WIDTH],
      rows: [new TableRow({ children: [
        cell([
          // Publication label + date on same row
          new Paragraph({
            alignment: AlignmentType.CENTER,
            spacing: { before: 0, after: 120, line: 240 },
            children: [
              new TextRun({ text: "CHORUS AI", bold: true, size: 16, color: GOLD, font: "Arial" }),
              new TextRun({ text: "   \u00B7   EARNINGS CALL INTELLIGENCE   \u00B7   ", size: 16, color: NAVY_FAINT, font: "Arial" }),
              new TextRun({ text: dateStr.toUpperCase(), size: 16, color: NAVY_FAINT, font: "Arial" }),
            ],
          }),

          // Company name — compact, not hero
          para(run(company, {
            bold: true, size: 48, color: WHITE, font: "Arial",
          }), { align: AlignmentType.CENTER, spaceAfter: 40 }),

          // Ticker · Quarter · Sector
          para([
            run(ticker, { size: 18, color: GOLD, font: "Arial", bold: true }),
            run("   \u00B7   ", { size: 18, color: NAVY_FAINT }),
            run(quarter + " Earnings Call", { size: 18, color: NAVY_FAINT, font: "Arial" }),
            ...(sector ? [
              run("   \u00B7   ", { size: 18, color: NAVY_FAINT }),
              run(sector, { size: 18, color: NAVY_FAINT, font: "Arial" }),
            ] : []),
          ], { align: AlignmentType.CENTER, spaceAfter: 0 }),

        ], { fill: NAVY, noBorder: true, padV: 140, padH: 300 }),
      ]})]
    }),

    // Gold rule — masthead bottom edge
    new Paragraph({
      children: [new TextRun({ text: "" })],
      border: { bottom: { style: BorderStyle.SINGLE, size: 16, color: GOLD, space: 1 } },
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

  // ── Headline — editorial, compact ───────────────────────────────────────
  elements.push(spacer(6));
  elements.push(new Paragraph({
    children: [new TextRun({
      text: headline,
      font: "Georgia",
      size: 34,
      bold: true,
      color: CHARCOAL,
    })],
    spacing: { before: 0, after: 60, line: 320 },
  }));

  // ── Deck copy — the editorial "why you should care" ────────────────────
  if (deckText) {
    elements.push(new Paragraph({
      children: [new TextRun({
        text: deckText,
        font: "Georgia",
        size: 21,
        italics: true,
        color: DARK_GRAY,
      })],
      spacing: { before: 0, after: 60, line: 280 },
    }));
  }

  // Gold rule
  elements.push(new Paragraph({
    children: [new TextRun({ text: "" })],
    border: { bottom: { style: BorderStyle.SINGLE, size: 6, color: GOLD, space: 1 } },
    spacing: { before: 0, after: 60 },
  }));

  elements.push(spacer(4));
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
    para(run("BY THE NUMBERS", { bold: true, size: 16, color: MID_GRAY, font: "Arial" }),
         { spaceAfter: 30 })
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
    const value = formatDisplayValue(m.reported_value);
    const label = m.metric_name || "";
    const delta = m.yoy_change || "";
    const vs    = m.vs_estimate || "";

    const shortLabel = label.length > 34 ? label.substring(0, 32) + "…" : label;
    let deltaColor = MID_GRAY;
    if (delta.startsWith("+")) deltaColor = GREEN;
    else if (delta.startsWith("-")) deltaColor = RED;

    const cardFill = i % 2 === 0 ? LIGHT_BG : WHITE;

    // Smaller font for long values, to keep them on one line
    const valueSize = value.length > 6 ? 40 : 52;
    return cell([
      para(run(shortLabel, { size: 16, color: MID_GRAY, font: "Arial" }),
           { align: AlignmentType.CENTER, spaceAfter: 50 }),
      para(run(value, { bold: true, size: valueSize, color: NAVY, font: "Arial" }),
           { align: AlignmentType.CENTER, spaceAfter: 20 }),
      delta
        ? para(run(delta, { bold: true, size: 22, color: deltaColor, font: "Arial" }),
               { align: AlignmentType.CENTER, spaceAfter: 20 })
        : spacer(0),
      vs
        ? para(run(vs, { size: 16, italics: true, color: MID_GRAY }),
               { align: AlignmentType.CENTER, spaceAfter: 0 })
        : spacer(0),
    ], { width: cardW, fill: cardFill, borderColor: BORDER, padV: 100, padH: 80 });
  });

  elements.push(new Table({
    width: { size: CONTENT_WIDTH, type: WidthType.DXA },
    columnWidths: financials.map(() => cardW),
    rows: [
      new TableRow({ children: stripCells }),
      new TableRow({ children: cardCells }),
    ],
  }));

  elements.push(spacer(4));
  return elements;
}

// =============================================================================
// BLOCK: THREE TAKEAWAYS
// =============================================================================
function buildTakeaways(snapshot) {
  const takeaways = (snapshot.key_takeaways || []);
  if (takeaways.length === 0) return [];

  const elements = [];
  elements.push(divider(BORDER, 4));
  elements.push(spacer(4));
  elements.push(
    para(run("THE STORY IN THREE POINTS", { bold: true, size: 16, color: MID_GRAY, font: "Arial" }),
         { spaceAfter: 40 })
  );

  const numW  = 440;
  const textW = CONTENT_WIDTH - numW;

  takeaways.forEach((t, i) => {
    const text = stripCitations(t.text || "").replace(/\*\*/g, "");
    const num  = String(t.number || i + 1);

    // Try to split into bold lead sentence + body
    const match = text.match(/^(.*?[.!?])\s+([\s\S]+)$/);
    const lead  = match ? match[1] : text;
    const body  = match ? match[2] : "";

    const cardFill = i === 0 ? GOLD_LIGHT : WHITE;
    const cardBorder = i === 0 ? GOLD : BORDER;

    const numberCell = cell(
      para(run(num, { bold: true, size: 40, color: WHITE, font: "Arial" }),
           { align: AlignmentType.CENTER, spaceAfter: 0 }),
      { width: numW, fill: NAVY, noBorder: true, padV: 100, padH: 60, vAlign: VerticalAlign.CENTER }
    );

    const textContent = [
      para(run(lead, { bold: true, size: 21, color: CHARCOAL, font: "Calibri" }),
           { spaceAfter: body ? 40 : 0 }),
    ];
    if (body) {
      textContent.push(
        para(run(body, { size: 20, color: DARK_GRAY, font: "Calibri" }),
             { spaceAfter: 0 })
      );
    }

    const textCell = cell(textContent, {
      width: textW,
      fill: cardFill,
      borderColor: cardBorder,
      padV: 100, padH: 180,
      vAlign: VerticalAlign.CENTER,
    });

    elements.push(new Table({
      width: { size: CONTENT_WIDTH, type: WidthType.DXA },
      columnWidths: [numW, textW],
      rows: [new TableRow({ children: [numberCell, textCell] })],
    }));
    elements.push(spacer(3));
  });

  elements.push(spacer(4));
  elements.push(divider(BORDER, 4));
  elements.push(spacer(6));
  return elements;
}

// =============================================================================
// BLOCK: SIGNALS AT A GLANCE
// =============================================================================
function buildSignals(sections) {
  const elements = [];

  elements.push(
    para(run("SIGNALS AT A GLANCE", { bold: true, size: 17, color: MID_GRAY, font: "Arial" }),
         { spaceAfter: 80, keepNext: true })
  );

  const greenItems = [];
  const redItems   = [];

  // Green flags: S2b claims explicitly tagged positive (fallback: grounded/derived if no valence data)
  if (sections.S2b) {
    const tagged = sections.S2b.claims.filter(c => c.signal_valence === "positive");
    const source = tagged.length > 0
      ? tagged
      : sections.S2b.claims.filter(c => c.claim_type === "grounded" || c.claim_type === "derived");
    source.slice(0, 4).forEach(c => greenItems.push(stripCitations(c.claim_text)));
  }
  // Watch points: S2c claims explicitly tagged negative (all S2c claims should be, but filter as safety net)
  if (sections.S2c) {
    const tagged = sections.S2c.claims.filter(c => c.signal_valence === "negative");
    const source = tagged.length > 0 ? tagged : sections.S2c.claims;
    source.slice(0, 4).forEach(c => redItems.push(stripCitations(c.claim_text)));
  }

  const maxRows = Math.max(greenItems.length, redItems.length, 1);
  const colW = Math.floor(CONTENT_WIDTH / 2);

  const headerRow = new TableRow({ children: [
    cell(
      para(run("+ GREEN FLAGS", { bold: true, size: 21, color: WHITE, font: "Arial" })),
      { width: colW, fill: "166534", noBorder: true, padV: 100 }
    ),
    cell(
      para(run("- WATCH POINTS", { bold: true, size: 21, color: WHITE, font: "Arial" })),
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

  elements.push(spacer(14));
  return elements;
}

// =============================================================================
// BLOCK: SCORECARD (radar chart + color-coded score table)
// =============================================================================
function buildScorecard(radarScores, chartPngPath) {
  const elements = [];

  elements.push(new Paragraph({ children: [new PageBreak()], spacing: { before: 0, after: 0 } }));
  elements.push(spacer(12));
  elements.push(
    para(run("EARNINGS CALL RADAR", { bold: true, size: 17, color: MID_GRAY, font: "Arial" }),
         { spaceAfter: 120 })
  );

  // Radar chart
  try {
    const imageBuffer = fs.readFileSync(chartPngPath);
    elements.push(new Paragraph({
      alignment: AlignmentType.CENTER,
      spacing: { before: 0, after: 200 },
      children: [new ImageRun({
        data: imageBuffer,
        transformation: { width: 400, height: 400 },
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

    const headerRow = new TableRow({ cantSplit: true, tableHeader: true, children: [
      cell(para(run("DIMENSION", { bold: true, size: 18, color: WHITE, font: "Arial" })),
           { width: labelW, fill: NAVY, noBorder: true }),
      cell(para(run("SCORE", { bold: true, size: 18, color: WHITE, font: "Arial" }),
               { align: AlignmentType.CENTER }),
           { width: scoreW, fill: NAVY, noBorder: true }),
      cell(para(run("RATIONALE", { bold: true, size: 18, color: WHITE, font: "Arial" })),
           { width: noteW, fill: NAVY, noBorder: true }),
    ]});

    const dataRows = radarScores.dimension_scores.map((d, i) => {
      const name      = DISPLAY_NAMES[d.dimension] || d.dimension;
      const score     = d.published_score;
      const rawRationale = (d.scoring_rationale || "").trim();
      const rationale = rawRationale.length > 8
        ? rawRationale.substring(0, 300)
        : "(Rationale unavailable — pipeline retry did not recover an explanation for this score.)";
      const rowFill   = i % 2 === 0 ? WHITE : LIGHT_BG;
      const tc        = scoreTextColor(score);

      return new TableRow({ cantSplit: true, children: [
        cell(para(run(name, { bold: true, size: 21, font: "Calibri" })),
             { width: labelW, fill: rowFill, borderColor: BORDER, padV: 160 }),
        cell([
          para(run(String(score), { bold: true, size: 36, color: tc, font: "Arial" }),
               { align: AlignmentType.CENTER, spaceAfter: 30 }),
          para(run(scoreBar(score), { size: 14, color: tc, font: "Arial" }),
               { align: AlignmentType.CENTER, spaceAfter: 0 }),
        ], { width: scoreW, fill: scoreColor(score), borderColor: BORDER, padV: 140 }),
        cell(para(run(rationale, { size: 19, italics: true, color: DARK_GRAY })),
             { width: noteW, fill: rowFill, borderColor: BORDER, padV: 160 }),
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
// S2b TWO-COLUMN CARD GRID
// Renders S2b as a clean 2×2 grid of cards: coloured header bar + body text.
// Each of the 4 mandatory subheadings gets its own card.
// =============================================================================
function renderS2bColumns(elements, processedParas, accent, accentBg) {
  // ---- Group into {heading, paras[]} blocks ----
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

  // Intro text (before first subheading) rendered full-width, then discard
  const introBlock = blocks[0] && blocks[0].heading === null ? blocks.shift() : null;
  if (introBlock && introBlock.paras.length > 0) {
    const introText = introBlock.paras.join(" ").replace(/\*\*/g, "");
    elements.push(new Paragraph({
      children: [new TextRun({ text: introText, font: "Calibri", size: 22, color: CHARCOAL })],
      spacing: { before: 0, after: 200, line: 320 },
    }));
  }

  // Helper: render one block's body paras as TextRun array for a cell
  function bodyRuns(block) {
    return block.paras.map(p => {
      const parts = p.replace(/\*\*/g, "").split(/(\d+\.?\d*%|\$[\d.,]+(?:\s*(?:billion|million|B|M))?)/gi);
      const runs = parts.map(part => {
        const isStat = /\d+\.?\d*%|\$[\d.,]+/.test(part);
        return new TextRun({
          text: part,
          font: isStat ? "Arial" : "Calibri",
          size: 21,
          bold: isStat,
          color: isStat ? NAVY : CHARCOAL,
        });
      });
      return new Paragraph({ children: runs, spacing: { before: 0, after: 120, line: 300 } });
    });
  }

  // Pair blocks into rows of 2
  const colW = Math.floor(CONTENT_WIDTH / 2);
  const cardBlocks = blocks.slice(0, 4); // max 4 cards
  // Pad to even number
  while (cardBlocks.length % 2 !== 0) cardBlocks.push({ heading: null, paras: [] });

  for (let i = 0; i < cardBlocks.length; i += 2) {
    const left  = cardBlocks[i];
    const right = cardBlocks[i + 1];

    function makeCard(block, w) {
      const headerPara = new Paragraph({
        children: [new TextRun({
          text: (block.heading || "").toUpperCase(),
          font: "Arial", size: 18, bold: true, color: "FFFFFF",
        })],
        spacing: { before: 0, after: 0, line: 240 },
      });

      const headerCell = cell(headerPara, {
        width: w, fill: accent, noBorder: true, padV: 120, padH: 200,
      });

      const bodyParas = block.paras.length > 0
        ? bodyRuns(block)
        : [new Paragraph({ children: [new TextRun({ text: "" })], spacing: { before: 0, after: 0 } })];

      const bodyCell = cell(bodyParas, {
        width: w, fill: accentBg, noBorder: true, padV: 140, padH: 200, vAlign: VerticalAlign.TOP,
      });

      return [headerCell, bodyCell];
    }

    const [lHead, lBody] = makeCard(left,  colW);
    const [rHead, rBody] = makeCard(right, colW);

    // Render as two stacked rows: header row + body row
    // cantSplit on every row prevents Word from breaking inside a row.
    // keepLines on the spacer glues it to the table so the pair won't orphan.
    elements.push(new Paragraph({ children: [new TextRun({ text: "" })], spacing: { before: 60, after: 0 }, keepNext: true }));
    elements.push(new Table({
      width: { size: CONTENT_WIDTH, type: WidthType.DXA },
      columnWidths: [colW, colW],
      rows: [
        new TableRow({ cantSplit: true, children: [lHead, rHead] }),
        new TableRow({ cantSplit: true, children: [lBody, rBody] }),
      ],
    }));
  }

  elements.push(spacer(8));
}

// =============================================================================
// S2c QUESTION LIST
// Renders S2c as a numbered list of pointed questions with a "why it matters" note.
// Parses **Question?** followed by a body line.
// =============================================================================
function renderS2cQuestions(elements, processedParas, accent, accentBg) {
  // Group into {question, body} pairs.
  // Handles two formats the model may produce:
  //   (a) **Question?**\nBody on next line
  //   (b) **Question?** Body on same line
  const items = [];
  let curr = null;
  processedParas.forEach(p => {
    // Check for inline format: **Question?** Body text
    const inlineMatch = p.match(/^\*\*(.+?\?)\*\*\s*([\s\S]+)$/);
    if (inlineMatch) {
      if (curr) items.push(curr);
      items.push({ question: inlineMatch[1].trim(), body: inlineMatch[2].replace(/\*\*/g, "").trim() });
      curr = null;
      return;
    }
    // Pure heading: **Question?**
    const hm = p.match(/^\*\*(.+)\*\*\s*$/);
    if (hm) {
      if (curr) items.push(curr);
      curr = { question: hm[1].trim(), body: "" };
    } else if (curr) {
      curr.body = p.replace(/\*\*/g, "").trim();
    }
  });
  if (curr) items.push(curr);

  const numW  = 380;
  const textW = CONTENT_WIDTH - numW;

  items.slice(0, 5).forEach((item, i) => {
    const numberCell = cell(
      para(run(String(i + 1), { bold: true, size: 36, color: WHITE, font: "Arial" }),
           { align: AlignmentType.CENTER, spaceAfter: 0 }),
      { width: numW, fill: accent, noBorder: true, padV: 120, padH: 60, vAlign: VerticalAlign.CENTER }
    );

    const textContent = [
      para(run(item.question, { bold: true, size: 21, color: NAVY, font: "Calibri" }),
           { spaceAfter: item.body ? 50 : 0 }),
    ];
    if (item.body) {
      textContent.push(
        para(run(item.body, { size: 19, italics: true, color: DARK_GRAY, font: "Calibri" }),
             { spaceAfter: 0 })
      );
    }

    const textCell = cell(textContent, {
      width: textW, fill: i % 2 === 0 ? accentBg : WHITE,
      borderColor: BORDER, padV: 120, padH: 200, vAlign: VerticalAlign.CENTER,
    });

    elements.push(new Table({
      width: { size: CONTENT_WIDTH, type: WidthType.DXA },
      columnWidths: [numW, textW],
      rows: [new TableRow({ cantSplit: true, children: [numberCell, textCell] })],
    }));
  });

  elements.push(spacer(8));
}

// =============================================================================
// S2f INDUSTRY VIEW — peer comparison table + stock reaction + 2-col narrative
// =============================================================================
function renderS2fLayout(elements, processedParas, accent, accentBg, snapshot, contextBundle) {
  // ---- Build peer comparison table ----
  const peerSummaries = (contextBundle && contextBundle.peer_summaries) || [];
  const stockReaction = (contextBundle && contextBundle.stock_reaction) || null;

  // Parse a metric value from key_metrics string array e.g. "Operating margin: 9.3%"
  function parsePeerMetric(metrics, label) {
    if (!metrics) return null;
    const hit = metrics.find(m => m.toLowerCase().startsWith(label.toLowerCase()));
    if (!hit) return null;
    return hit.split(":")[1]?.trim() || null;
  }

  // Get subject company's operating margin from snapshot key_financials
  function subjectMargin() {
    if (!snapshot || !snapshot.key_financials) return null;
    const hit = snapshot.key_financials.find(m =>
      /operating margin/i.test(m.metric_name)
    );
    return hit ? String(hit.reported_value).replace("%", "").trim() : null;
  }

  const subjectTicker  = (snapshot && snapshot.ticker)       || "";
  const subjectMarginVal = subjectMargin();

  // Build rows: subject first, then peers sorted by margin desc
  const rows = [];
  if (subjectMarginVal) {
    rows.push({ ticker: subjectTicker, margin: parseFloat(subjectMarginVal), marginStr: subjectMarginVal + "%", isSubject: true });
  }
  peerSummaries.forEach(p => {
    const m = parsePeerMetric(p.key_metrics, "Operating margin");
    const r = parsePeerMetric(p.key_metrics, "Revenue");
    if (m) {
      rows.push({ ticker: p.ticker, margin: parseFloat(m), marginStr: m, revenue: r, isSubject: false });
    }
  });
  rows.sort((a, b) => b.margin - a.margin);

  if (rows.length > 0) {
    const tickerW   = 900;
    const marginW   = 1200;
    const revenueW  = 1300;
    const gapW      = 1100;
    const barW      = CONTENT_WIDTH - tickerW - marginW - revenueW - gapW;

    // Header row
    const headerRow = new TableRow({ children: [
      cell(para(run("COMPANY",        { size: 16, bold: true, color: WHITE, font: "Arial" })), { width: tickerW,  fill: accent, noBorder: true, padV: 80, padH: 120 }),
      cell(para(run("OP. MARGIN",     { size: 16, bold: true, color: WHITE, font: "Arial" }), { align: AlignmentType.CENTER }), { width: marginW,  fill: accent, noBorder: true, padV: 80, padH: 80 }),
      cell(para(run("REVENUE",        { size: 16, bold: true, color: WHITE, font: "Arial" }), { align: AlignmentType.CENTER }), { width: revenueW, fill: accent, noBorder: true, padV: 80, padH: 80 }),
      cell(para(run("vs " + subjectTicker, { size: 16, bold: true, color: WHITE, font: "Arial" }), { align: AlignmentType.CENTER }), { width: gapW,     fill: accent, noBorder: true, padV: 80, padH: 80 }),
      cell(para(run("",               { size: 16 })), { width: barW, fill: accent, noBorder: true, padV: 80, padH: 0 }),
    ]});

    const dataRows = rows.map((r, i) => {
      const isSubj = r.isSubject;
      const rowBg  = isSubj ? accentBg : (i % 2 === 0 ? WHITE : "F9FAFB");
      const subjectMarginNum = rows.find(x => x.isSubject)?.margin || 0;
      const gapNum = r.margin - subjectMarginNum;
      const gapStr = isSubj ? "—" : (gapNum > 0 ? `+${gapNum.toFixed(1)}pp` : `${gapNum.toFixed(1)}pp`);
      const gapColor = isSubj ? MID_GRAY : (gapNum >= 0 ? GREEN : RED);

      // Bar: proportional fill based on margin / max margin
      const maxMargin = rows[0].margin;
      const barPct = Math.round((r.margin / maxMargin) * 100);
      const barFilled = Math.round(barW * barPct / 100);
      const barEmpty  = barW - barFilled;

      return new TableRow({ children: [
        cell(para(run(r.ticker, { bold: isSubj, size: isSubj ? 22 : 20, color: isSubj ? NAVY : CHARCOAL, font: "Arial" })),
             { width: tickerW, fill: rowBg, borderColor: BORDER, padV: 100, padH: 120 }),
        cell(para(run(r.marginStr + "%", { bold: isSubj, size: isSubj ? 26 : 22, color: isSubj ? accent : CHARCOAL, font: "Arial" }), { align: AlignmentType.CENTER }),
             { width: marginW, fill: rowBg, borderColor: BORDER, padV: 100, padH: 80 }),
        cell(para(run(r.revenue || "—", { size: 20, color: DARK_GRAY, font: "Calibri" }), { align: AlignmentType.CENTER }),
             { width: revenueW, fill: rowBg, borderColor: BORDER, padV: 100, padH: 80 }),
        cell(para(run(gapStr, { bold: true, size: 20, color: gapColor, font: "Arial" }), { align: AlignmentType.CENTER }),
             { width: gapW, fill: rowBg, borderColor: BORDER, padV: 100, padH: 80 }),
        // Inline margin bar
        new TableCell({
          width: { size: barW, type: WidthType.DXA },
          borders: { top: { style: BorderStyle.NONE }, bottom: { style: BorderStyle.NONE }, left: { style: BorderStyle.NONE }, right: { style: BorderStyle.NONE } },
          shading: { type: ShadingType.SOLID, fill: rowBg, color: rowBg },
          margins: { top: 0, bottom: 0, left: 0, right: 0 },
          children: [new Table({
            width: { size: barW, type: WidthType.DXA },
            columnWidths: [Math.max(barFilled, 1), Math.max(barEmpty, 1)],
            rows: [new TableRow({ children: [
              cell(para(run("", { size: 2 })), { width: Math.max(barFilled, 1), fill: isSubj ? accent : "9CA3AF", noBorder: true, padV: 60, padH: 0 }),
              cell(para(run("", { size: 2 })), { width: Math.max(barEmpty, 1),  fill: rowBg, noBorder: true, padV: 60, padH: 0 }),
            ]})]
          })],
        }),
      ]});
    });

    elements.push(new Table({
      width: { size: CONTENT_WIDTH, type: WidthType.DXA },
      columnWidths: [tickerW, marginW, revenueW, gapW, barW],
      rows: [headerRow, ...dataRows],
    }));
    elements.push(spacer(4));
  }

  // ---- Stock reaction badge ----
  if (stockReaction && stockReaction.reaction_pct !== undefined) {
    const pct     = stockReaction.reaction_pct;
    const label   = stockReaction.reaction_label || "";
    const pctStr  = (pct >= 0 ? "+" : "") + pct.toFixed(1) + "%";
    const color   = pct >= 0 ? GREEN : RED;
    elements.push(para([
      run("MARKET REACTION  ", { size: 15, bold: true, color: MID_GRAY, font: "Arial" }),
      run(pctStr, { size: 15, bold: true, color, font: "Arial" }),
      run("  on earnings day  ·  " + label.toUpperCase(), { size: 15, color: MID_GRAY, font: "Arial" }),
    ], { spaceAfter: 80 }));
    elements.push(spacer(4));
  }

  // ---- Narrative: 2-column subheading grid (reuse S2a block logic) ----
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

  const colW = Math.floor(CONTENT_WIDTH / 2);

  function blockToDocx(block) {
    const out = [];
    if (block.heading) {
      out.push(new Paragraph({
        children: [new TextRun({ text: block.heading.toUpperCase(), font: "Calibri", size: 21, bold: true, color: NAVY })],
        spacing: { before: 60, after: 100 },
        border: { bottom: { style: BorderStyle.SINGLE, size: 8, color: accent, space: 4 } },
      }));
    }
    block.paras.forEach(p => {
      const parts = p.replace(/\*\*/g, "").split(/(\d+\.?\d*%|\$[\d.,]+(?:\s*(?:billion|million|B|M))?)/gi);
      const runs  = parts.map(part => {
        const isStat = /\d+\.?\d*%|\$[\d.,]+/.test(part);
        return new TextRun({ text: part, font: isStat ? "Arial" : "Calibri", size: isStat ? 22 : 21, bold: isStat, color: isStat ? NAVY : CHARCOAL });
      });
      out.push(new Paragraph({ children: runs, spacing: { before: 0, after: 140, line: 300 } }));
    });
    return out;
  }

  for (let i = 0; i < blocks.length; i += 2) {
    const leftDocx  = blockToDocx(blocks[i]);
    const rightDocx = blocks[i + 1] ? blockToDocx(blocks[i + 1]) : [new Paragraph({ children: [new TextRun({ text: "" })] })];
    elements.push(spacer(4));
    elements.push(new Table({
      width: { size: CONTENT_WIDTH, type: WidthType.DXA },
      columnWidths: [colW, colW],
      rows: [new TableRow({ cantSplit: true, children: [
        cell(leftDocx,  { width: colW, noBorder: true, padV: 80, padH: 180, vAlign: VerticalAlign.TOP }),
        cell(rightDocx, { width: colW, noBorder: true, padV: 80, padH: 180, vAlign: VerticalAlign.TOP }),
      ]})],
    }));
  }

  elements.push(spacer(8));
}

// =============================================================================
// S2a TWO-COLUMN LAYOUT
// Groups the S2a narrative into subheading+body blocks and renders them
// in a 2-column magazine grid. Numbers are bolded inline so they pop.
// =============================================================================
function renderS2aColumns(elements, processedParas, accent, accentBg) {
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
    let lead = m ? m[1] : clean;
    let rest = m ? m[2] : "";
    if (lead.length > 130) {
      const cutoff = clean.lastIndexOf(" ", 120);
      lead = cutoff > 60 ? clean.substring(0, cutoff) : clean.substring(0, 120);
      rest = clean.substring(lead.length).trim();
    }
    const cleanIntro = p.replace(/\*\*/g, "");
    elements.push(new Paragraph({
      children: [new TextRun({ text: cleanIntro, font: "Calibri", size: 21, color: CHARCOAL })],
      spacing: { before: 0, after: 160, line: 300 },
    }));
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
          font: "Calibri", size: 21, bold: true, color: NAVY,
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
        spacing: { before: 0, after: 140, line: 300 },
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
      rows: [new TableRow({ cantSplit: true, children: [
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
function buildNarrative(sections, snapshot, contextBundle) {
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
      id: "S2f",
      label: "THE INDUSTRY VIEW",
      number: "04",
      accent: "0891B2",
      accentBg: "ECFEFF",
      fill: "164E63",
      subtitleColor: "67E8F9",
      subtitle: "Peer benchmarking & competitive positioning",
    },
  ];

  SECTION_META.forEach(({ id, label, number, accent, accentBg, fill, subtitleColor, subtitle }) => {
    // Section divider — breathing room, no forced page break so Word can flow naturally
    elements.push(spacer(20));

    // ---- MAGAZINE-STYLE SECTION HEADER as a Paragraph ----
    // Using a Paragraph (not a Table) so keepNext: true reliably keeps the header
    // glued to the first line of section content in Word's layout engine.
    elements.push(new Paragraph({
      shading: { type: ShadingType.SOLID, fill: fill, color: fill },
      border: {
        top:    { style: BorderStyle.NONE, size: 0, color: fill },
        bottom: { style: BorderStyle.NONE, size: 0, color: fill },
        right:  { style: BorderStyle.NONE, size: 0, color: fill },
        left:   { style: BorderStyle.SINGLE, size: 36, color: accent, space: 10 },
      },
      spacing: { before: 160, after: 160, line: 320, lineRule: "auto" },
      indent: { left: 420 },
      keepNext: true,
      keepLines: true,
      children: [
        new TextRun({ text: number, bold: true, size: 60, color: accent, font: "Arial" }),
        new TextRun({ text: "  " + label, bold: true, size: 22, color: "FFFFFF", font: "Arial", break: 1 }),
        new TextRun({ text: subtitle, size: 18, italics: true, color: subtitleColor, font: "Calibri", break: 1 }),
      ],
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

    elements.push(spacer(10));

    // ---- Parse narrative: separate "to watch" list for S2d ----
    const narrative = stripCitations(section.narrative || "");
    // Split on any newline(s) — handles both \n and \n\n from different LLMs.
    // Then break any remaining long paragraphs at sentence boundaries.
    const rawParas = narrative
      .split(/\n+/)
      .map(p => p.trim())
      .filter(Boolean)
      .flatMap(p => breakLongParagraph(p));
    let isFirst = true;
    let bodyParaCount = 0;
    let pullQuoteInserted = false;
    let watchListItems = [];
    const processedParas = [];
    // Pick a pull quote: longest sentence from the narrative (>60 chars, not a subheading)
    const pullQuoteText = rawParas
      .filter(p => !p.match(/^\*\*[^*]+\*\*\s*$/) && p.length > 60)
      .map(p => {
        const sentences = p.match(/[^.!?]+[.!?]+/g) || [];
        return sentences.reduce((a, b) => b.length > a.length ? b : a, "");
      })
      .reduce((a, b) => b.length > a.length ? b : a, "")
      .replace(/\*\*/g, "").trim() || null;

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
      renderS2aColumns(elements, processedParas, accent, accentBg);
    } else if (id === "S2b") {
      renderS2bColumns(elements, processedParas, accent, accentBg);
    } else if (id === "S2c") {
      renderS2cQuestions(elements, processedParas, accent, accentBg);
    } else if (id === "S2f") {
      renderS2fLayout(elements, processedParas, accent, accentBg, snapshot, contextBundle);
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
              para(run(subheadMatch[1].toUpperCase(), { bold: true, size: 22, color: NAVY, font: "Calibri" }),
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
        // Guard: if the "lead" is too long (no early period), cap it at 120 chars
        let leadSentence = firstSentMatch ? firstSentMatch[1] : cleanText;
        let rest = firstSentMatch ? firstSentMatch[2] : "";
        if (leadSentence.length > 130) {
          // Hard-split at word boundary near 120 chars
          const cutoff = cleanText.lastIndexOf(" ", 120);
          leadSentence = cutoff > 60 ? cleanText.substring(0, cutoff) : cleanText.substring(0, 120);
          rest = cleanText.substring(leadSentence.length).trim();
        }

        const cleanParts = cleanText.split(/(\*\*[^*]+\*\*)/g);
        const leadRuns = cleanParts.map(part => {
          if (part.startsWith("**") && part.endsWith("**")) {
            return new TextRun({ text: part.replace(/\*\*/g, ""), font: "Calibri", size: 22, bold: true, color: CHARCOAL });
          }
          return new TextRun({ text: part, font: "Calibri", size: 22, color: CHARCOAL });
        });

        elements.push(new Paragraph({
          children: leadRuns,
          spacing: { before: 0, after: 160, line: 320 },
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
        spacing: { before: 0, after: 160, line: 320 },
      }));

      bodyParaCount++;

      // Insert pull quote after 2nd body paragraph
      if (!pullQuoteInserted && bodyParaCount === 2 && pullQuoteText) {
        pullQuoteInserted = true;
        buildPullQuote(pullQuoteText, accent).forEach(el => elements.push(el));
      }
    }); } // end else (non-S2a rendering)

    elements.push(spacer(2));
  });

  return elements;
}

// =============================================================================
// BLOCK: VERIFICATION APPENDIX
// =============================================================================
function buildVerification(verification) {
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
// =============================================================================
// ECON EXPERT'S TAKE (S7) — Theory Verdict
// Two color-coded boxes: Smart Moves (green) + Questionable Calls (amber/red).
// =============================================================================
function buildEconExpert(econExpert) {
  if (!econExpert) return [];
  const smartMoves      = econExpert.smart_moves      || [];
  const questionable    = econExpert.questionable_calls || [];
  if (smartMoves.length === 0 && questionable.length === 0) return [];

  const elements = [];

  const SMART_GREEN  = "1D6A3A";   // deep green for the "smart" box
  const SMART_BG     = "EAF4ED";   // pale green background
  const RISKY_AMBER  = "8B2500";   // deep amber/red for "questionable" box
  const RISKY_BG     = "FDF0EB";   // pale amber background

  elements.push(spacer(20, true));

  // Section banner
  const stripeW = 80;
  const headerW = CONTENT_WIDTH - stripeW;
  elements.push(new Table({
    width: { size: CONTENT_WIDTH, type: WidthType.DXA },
    columnWidths: [stripeW, headerW],
    rows: [new TableRow({ cantSplit: true, children: [
      cell(para(run("", { size: 2 })),
           { width: stripeW, fill: "1A5276", noBorder: true, padV: 160, padH: 0 }),
      cell([
        para(run("THEORY VERDICT", { bold: true, size: 17, color: GOLD, font: "Arial" }),
             { spaceAfter: 40 }),
        para(run("What business theory says about this company's choices", {
          size: 15, italics: false, color: NAVY_FAINT, font: "Arial"
        }), { spaceAfter: 0 }),
      ], { width: headerW, fill: NAVY, noBorder: true, padV: 160, padH: 260, vAlign: VerticalAlign.CENTER }),
    ]})]
  }));

  elements.push(spacer(10));

  // Helper: render one theory point row inside a box
  function theoryPointRow(point, accentColor) {
    return new TableRow({ cantSplit: true, children: [
      cell([
        para(run(point.concept || "", { bold: true, size: 21, color: accentColor, font: "Arial" }),
             { spaceAfter: 40 }),
        para(run((point.explanation || "").replace(/\*\*/g, ""), { size: 20, color: CHARCOAL, font: "Calibri" }),
             { spaceAfter: 0, lineSpacing: 300 }),
      ], { noBorder: true, padV: 140, padH: 200 }),
    ]});
  }

  // Helper: render a full box (header + rows)
  function theoryBox(label, points, accentColor, bgColor) {
    if (!points || points.length === 0) return;

    // Box header
    elements.push(new Table({
      width: { size: CONTENT_WIDTH, type: WidthType.DXA },
      columnWidths: [CONTENT_WIDTH],
      rows: [new TableRow({ cantSplit: true, children: [
        cell(para(run(label, { bold: true, size: 19, color: "FFFFFF", font: "Arial" }),
             { spaceAfter: 0 }),
             { fill: accentColor, noBorder: true, padV: 120, padH: 200 }),
      ]})]
    }));

    // Each theory point
    points.forEach((point, idx) => {
      const isLast = idx === points.length - 1;
      elements.push(new Table({
        width: { size: CONTENT_WIDTH, type: WidthType.DXA },
        columnWidths: [CONTENT_WIDTH],
        rows: [theoryPointRow(point, accentColor)],
        ...(isLast ? {} : {}),
      }));
      // Thin divider between points (not after last)
      if (!isLast) {
        elements.push(new Paragraph({
          children: [new TextRun({ text: "" })],
          border: { bottom: { style: BorderStyle.SINGLE, size: 2, color: "CCCCCC", space: 1 } },
          spacing: { before: 0, after: 0 },
        }));
      }
    });

    elements.push(spacer(6));
  }

  theoryBox("✓  THE SMART MOVES", smartMoves, SMART_GREEN, SMART_BG);
  elements.push(spacer(6));
  theoryBox("⚑  THE QUESTIONABLE CALLS", questionable, RISKY_AMBER, RISKY_BG);

  // Disclaimer
  elements.push(spacer(6));
  elements.push(para(
    run("Theory Verdict applies academic frameworks to reported results and does not constitute investment advice.", {
      size: 16, italics: true, color: MID_GRAY, font: "Calibri"
    }),
    { spaceAfter: 0 }
  ));

  elements.push(spacer(12));
  return elements;
}


// =============================================================================
// EDITORIAL COMMENTARY (S6 — The Lex Writer)
// =============================================================================
function buildEditorial(editorial) {
  if (!editorial || !editorial.narrative) return [];
  const elements = [];

  elements.push(spacer(20, true));  // keepNext: anchors spacer to editorial header below

  // Section banner — accent stripe left + navy header panel
  const stripeW = 80;
  const headerW = CONTENT_WIDTH - stripeW;
  elements.push(new Table({
    width: { size: CONTENT_WIDTH, type: WidthType.DXA },
    columnWidths: [stripeW, headerW],
    rows: [new TableRow({ cantSplit: true, children: [
      cell(para(run("", { size: 2 })),
           { width: stripeW, fill: GOLD, noBorder: true, padV: 160, padH: 0 }),
      cell([
        para(run("EDITORIAL", { bold: true, size: 17, color: GOLD, font: "Arial" }),
             { spaceAfter: 40 }),
        para(run("Analysis  \u00B7  Independent Perspective", {
          size: 15, italics: false, color: NAVY_FAINT, font: "Arial"
        }), { spaceAfter: 0, keepNext: true }),
      ], { width: headerW, fill: NAVY, noBorder: true, padV: 160, padH: 260, vAlign: VerticalAlign.CENTER }),
    ]})]
  }));

  elements.push(spacer(8));

  // Editorial prose — Georgia serif, proper FT Lex layout
  const rawParas = editorial.narrative.split(/\n+/).map(p => p.trim()).filter(Boolean).flatMap(p => breakLongParagraph(p));

  rawParas.forEach((p, i) => {
    const cleaned = stripCitations(p);
    if (i === 0) {
      // Lede paragraph: large Georgia serif, drop cap feel
      const firstSentMatch = cleaned.match(/^(.*?[.!?])\s*([\s\S]*)$/);
      const lede = firstSentMatch ? firstSentMatch[1] : cleaned;
      const rest = firstSentMatch ? firstSentMatch[2] : "";

      elements.push(new Paragraph({
        children: [
          new TextRun({ text: lede, font: "Georgia", size: 28, bold: true, color: NAVY }),
          ...(rest ? [new TextRun({ text: "  " + rest, font: "Georgia", size: 24, italics: true, color: DARK_GRAY })] : []),
        ],
        spacing: { before: 0, after: 200, line: 360 },
        indent: { left: 0, right: 0 },
      }));
    } else {
      // Body paragraphs: Georgia, normal weight, generous leading
      elements.push(new Paragraph({
        children: [new TextRun({ text: cleaned, font: "Georgia", size: 22, color: CHARCOAL })],
        spacing: { before: 0, after: 160, line: 320 },
      }));
    }
  });

  // Hairline rule + disclaimer
  elements.push(spacer(6));
  elements.push(new Paragraph({
    children: [new TextRun({ text: "" })],
    border: { bottom: { style: BorderStyle.SINGLE, size: 4, color: GOLD, space: 1 } },
    spacing: { before: 0, after: 80 },
  }));
  elements.push(para(
    run("This commentary is the analytical judgment of the Chorus AI system and does not constitute investment advice.", {
      size: 16, italics: true, color: MID_GRAY, font: "Calibri"
    }),
    { spaceAfter: 0 }
  ));

  elements.push(spacer(12));
  return elements;
}


// =============================================================================
// CONTEXT PANEL — Historical trend chart + consensus estimates + stock reaction
// =============================================================================
function buildContextPanel(contextBundle) {
  if (!contextBundle) return [];
  const elements = [];

  const hasConsensus = contextBundle.consensus_estimates && contextBundle.consensus_estimates.length > 0;
  const hasPrior = contextBundle.prior_quarter_summaries && contextBundle.prior_quarter_summaries.length > 0;

  if (!hasConsensus && !hasPrior) return [];

  elements.push(spacer(8));

  // Consensus vs. actual row (full-width)
  if (hasConsensus) {
    const colW = [1400, 1200, 1200, 1500];
    const totalW = colW.reduce((a, b) => a + b, 0);

    const consensusRows = contextBundle.consensus_estimates.map(est => {
      const verdictColor = est.verdict === 'Beat' ? GREEN : est.verdict === 'Miss' ? RED : CHARCOAL;
      return new TableRow({ children: [
        cell(para(run(est.metric, { size: 18, bold: true, color: CHARCOAL })),
             { width: colW[0], fill: LIGHT_BG, noBorder: true, padV: 80, padH: 120 }),
        cell(para(run(est.estimate || '—', { size: 18, color: MID_GRAY })),
             { width: colW[1], fill: WHITE, noBorder: true, padV: 80, padH: 120 }),
        cell(para(run(est.actual || '—', { size: 18, color: CHARCOAL, bold: true })),
             { width: colW[2], fill: WHITE, noBorder: true, padV: 80, padH: 120 }),
        cell(para(run(`${est.verdict || ''} ${est.surprise_pct || ''}`.trim(), { size: 18, bold: true, color: verdictColor })),
             { width: colW[3], fill: WHITE, noBorder: true, padV: 80, padH: 120 }),
      ]});
    });

    elements.push(spacer(6));
    elements.push(para(run("CONSENSUS vs. ACTUAL", { bold: true, size: 17, color: MID_GRAY, font: "Arial" }), { spaceAfter: 80 }));
    elements.push(new Table({
      width: { size: totalW, type: WidthType.DXA },
      columnWidths: colW,
      rows: [
        new TableRow({ tableHeader: true, children: [
          cell(para(run("Metric",   { size: 17, bold: true, color: MID_GRAY })), { width: colW[0], fill: LIGHT_BG, noBorder: true, padV: 60, padH: 120 }),
          cell(para(run("Estimate", { size: 17, bold: true, color: MID_GRAY })), { width: colW[1], fill: LIGHT_BG, noBorder: true, padV: 60, padH: 120 }),
          cell(para(run("Actual",   { size: 17, bold: true, color: MID_GRAY })), { width: colW[2], fill: LIGHT_BG, noBorder: true, padV: 60, padH: 120 }),
          cell(para(run("Result",   { size: 17, bold: true, color: MID_GRAY })), { width: colW[3], fill: LIGHT_BG, noBorder: true, padV: 60, padH: 120 }),
        ]}),
        ...consensusRows,
      ],
    }));
  }

  elements.push(spacer(8));
  return elements;
}


async function main() {
  const args = process.argv.slice(2);
  if (args.length < 2) {
    console.error("Usage: node format_report.js <report_json> <output_docx>");
    process.exit(1);
  }

  const [reportJsonPath, outputDocxPath] = args;
  const reportData = JSON.parse(fs.readFileSync(reportJsonPath, 'utf8'));
  const { snapshot, editorial, econ_expert, sections, context_bundle, verification } = reportData;

  // Build verification summary for header badge
  const groundingVals = verification && verification.source_grounding_scores
    ? Object.values(verification.source_grounding_scores) : [];
  const avgGrounding = groundingVals.length
    ? groundingVals.reduce((a, b) => a + b, 0) / groundingVals.length : null;

  const verificationSummary = {
    avg_grounding: avgGrounding ? `${(avgGrounding * 100).toFixed(0)}%` : "—",
    contradictions: verification
      ? Object.values(verification.contradiction_counts || {}).reduce((a, b) => a + b, 0) : "—",
  };

  const children = [
    ...buildHeader(snapshot),
    ...buildHeadline(snapshot, verificationSummary),
    ...buildMetricCards(snapshot),
    ...buildTakeaways(snapshot),
    ...buildEditorial(editorial),
    ...buildContextPanel(context_bundle),
    ...buildSignals(sections),
    ...buildNarrative(sections, snapshot, context_bundle),
    ...buildEconExpert(econ_expert),
    ...buildVerification(verification),
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
          // US Letter — 8.5" × 11" in twips (1 inch = 1440 twips)
          size: { width: 12240, height: 15840 },
          // Print-quality margins: 1" top/bottom, 0.9" sides
          margin: { top: 1440, right: 1300, bottom: 1440, left: 1300 },
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
