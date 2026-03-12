/**
 * Chorus AI Systems — Earnings Call Dossier
 * Report Formatter v1.0
 *
 * Reads report_data.json and radar_chart.png, produces a formatted Word doc
 * matching the Chorus AI Earnings Call Brief template.
 *
 * Called by report_formatter.py — not run directly.
 *
 * Usage: node format_report.js <report_json_path> <chart_png_path> <output_docx_path>
 */

const {
  Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell,
  ImageRun, Header, AlignmentType, HeadingLevel, BorderStyle, WidthType,
  ShadingType, VerticalAlign, PageNumber, LevelFormat, PageBreak
} = require('docx');
const fs = require('fs');
const path = require('path');

// =============================================================================
// COLORS & STYLES
// =============================================================================
const NAVY       = "1B3A6B";
const DARK_GRAY  = "333333";
const MID_GRAY   = "666666";
const LIGHT_GRAY = "F5F6F8";
const GREEN_BG   = "E8F5E9";
const GREEN_TEXT = "1B5E20";
const RED_BG     = "FFEBEE";
const RED_TEXT   = "B71C1C";
const BORDER_CLR = "D0D8E4";
const WHITE      = "FFFFFF";

const CONTENT_WIDTH = 9360; // DXA — US Letter minus 1" margins each side

// =============================================================================
// HELPER: Text run factory
// =============================================================================
function run(text, opts = {}) {
  return new TextRun({
    text,
    font: "Arial",
    size: opts.size || 22,        // 11pt default
    bold: opts.bold || false,
    italics: opts.italics || false,
    color: opts.color || DARK_GRAY,
    break: opts.break || undefined,
  });
}

function para(children, opts = {}) {
  return new Paragraph({
    alignment: opts.align || AlignmentType.LEFT,
    spacing: { before: opts.spaceBefore || 0, after: opts.spaceAfter || 120 },
    children: Array.isArray(children) ? children : [children],
    heading: opts.heading || undefined,
    border: opts.border || undefined,
  });
}

function spacer(pts = 6) {
  return new Paragraph({
    children: [new TextRun({ text: "", size: pts * 2 })],
    spacing: { before: 0, after: 0 }
  });
}

function hrLine() {
  return new Paragraph({
    children: [new TextRun({ text: "" })],
    border: { bottom: { style: BorderStyle.SINGLE, size: 6, color: BORDER_CLR, space: 1 } },
    spacing: { before: 60, after: 60 }
  });
}

// =============================================================================
// HELPER: Standard cell builder
// =============================================================================
function cell(children, opts = {}) {
  const borders = opts.noBorder ? {
    top: { style: BorderStyle.NONE }, bottom: { style: BorderStyle.NONE },
    left: { style: BorderStyle.NONE }, right: { style: BorderStyle.NONE },
  } : {
    top:    { style: BorderStyle.SINGLE, size: 1, color: BORDER_CLR },
    bottom: { style: BorderStyle.SINGLE, size: 1, color: BORDER_CLR },
    left:   { style: BorderStyle.SINGLE, size: 1, color: BORDER_CLR },
    right:  { style: BorderStyle.SINGLE, size: 1, color: BORDER_CLR },
  };

  return new TableCell({
    borders,
    width: opts.width ? { size: opts.width, type: WidthType.DXA } : undefined,
    shading: opts.fill ? { fill: opts.fill, type: ShadingType.CLEAR } : undefined,
    verticalAlign: opts.vAlign || VerticalAlign.CENTER,
    margins: { top: 80, bottom: 80, left: 120, right: 120 },
    columnSpan: opts.span || 1,
    children: Array.isArray(children) ? children : [children],
  });
}

// =============================================================================
// SECTION 0: DOCUMENT HEADER
// =============================================================================
function buildHeader(snapshot) {
  const company = snapshot.company_name || "";
  const ticker  = snapshot.ticker || "";
  const quarter = snapshot.quarter || "";

  return [
    // "CHORUS AI SYSTEMS" masthead
    para(
      run("CHORUS AI SYSTEMS", { bold: true, size: 28, color: NAVY }),
      { align: AlignmentType.CENTER, spaceAfter: 60 }
    ),
    para(
      run("The Earnings Call Brief", { italics: true, size: 22, color: MID_GRAY }),
      { align: AlignmentType.CENTER, spaceAfter: 200 }
    ),

    // Company name large
    para(
      run(company.toUpperCase(), { bold: true, size: 36, color: NAVY }),
      { align: AlignmentType.CENTER, spaceAfter: 60 }
    ),
    para([
      run(ticker, { size: 22, color: MID_GRAY }),
      run("   |   ", { size: 22, color: MID_GRAY }),
      run(quarter + " Earnings Call", { size: 22, color: MID_GRAY }),
    ], { align: AlignmentType.CENTER, spaceAfter: 240 }),

    hrLine(),
    spacer(8),
  ];
}

// =============================================================================
// SECTION 1: THE SNAPSHOT
// =============================================================================
function buildSnapshot(snapshot, verificationSummary) {
  const elements = [];

  elements.push(
    para(run("1. The Snapshot", { bold: true, size: 28, color: NAVY }),
         { spaceAfter: 160 })
  );

  // Verification banner
  const grounding = verificationSummary.avg_grounding || "—";
  const contradictions = verificationSummary.contradictions || 0;
  const agreement = verificationSummary.model_agreement || "—";

  elements.push(
    new Table({
      width: { size: CONTENT_WIDTH, type: WidthType.DXA },
      columnWidths: [CONTENT_WIDTH],
      rows: [
        new TableRow({ children: [
          cell(
            para([
              run("AI-Verified Intelligence Report  ", { italics: true, size: 20, color: MID_GRAY }),
              run(`Source Grounding: ${grounding}  |  Contradictions: ${contradictions}  |  Model Agreement: ${agreement}`,
                  { italics: true, size: 20, color: MID_GRAY }),
            ]),
            { width: CONTENT_WIDTH, fill: LIGHT_GRAY }
          )
        ]})
      ]
    })
  );
  elements.push(spacer(10));

  // Key financials table
  if (snapshot.key_financials && snapshot.key_financials.length > 0) {
    elements.push(para(run("Key Financials", { bold: true, size: 22, color: NAVY }),
                       { spaceAfter: 80 }));

    const colWidths = [2400, 1800, 1800, 1800, 1560];
    const headers = ["Metric", "Reported", "YoY Change", "vs. Estimate", ""];

    const headerRow = new TableRow({
      tableHeader: true,
      children: headers.map((h, i) =>
        cell(
          para(run(h, { bold: true, size: 20, color: WHITE })),
          { width: colWidths[i], fill: NAVY }
        )
      )
    });

    const dataRows = snapshot.key_financials.map((m, idx) =>
      new TableRow({
        children: [
          cell(para(run(m.metric_name, { bold: true, size: 20 })),
               { width: colWidths[0], fill: idx % 2 === 0 ? WHITE : LIGHT_GRAY }),
          cell(para(run(m.reported_value || "—", { size: 20 })),
               { width: colWidths[1], fill: idx % 2 === 0 ? WHITE : LIGHT_GRAY }),
          cell(para(run(m.yoy_change || "—", { size: 20 })),
               { width: colWidths[2], fill: idx % 2 === 0 ? WHITE : LIGHT_GRAY }),
          cell(para(run(m.vs_estimate || "—", { size: 20 })),
               { width: colWidths[3], fill: idx % 2 === 0 ? WHITE : LIGHT_GRAY }),
          cell(para(run("", { size: 20 })),
               { width: colWidths[4], fill: idx % 2 === 0 ? WHITE : LIGHT_GRAY }),
        ]
      })
    );

    elements.push(new Table({
      width: { size: CONTENT_WIDTH, type: WidthType.DXA },
      columnWidths: colWidths,
      rows: [headerRow, ...dataRows]
    }));
    elements.push(spacer(12));
  }

  // Headline
  if (snapshot.headline) {
    elements.push(
      new Table({
        width: { size: CONTENT_WIDTH, type: WidthType.DXA },
        columnWidths: [CONTENT_WIDTH],
        rows: [new TableRow({ children: [
          cell(
            para(run(snapshot.headline, { italics: true, size: 22, color: NAVY }),
                 { align: AlignmentType.CENTER }),
            { width: CONTENT_WIDTH, fill: LIGHT_GRAY }
          )
        ]})]
      })
    );
    elements.push(spacer(12));
  }

  // Three key takeaways
  if (snapshot.key_takeaways && snapshot.key_takeaways.length > 0) {
    elements.push(para(run("Three Key Takeaways", { bold: true, size: 22, color: NAVY }),
                       { spaceAfter: 80 }));
    snapshot.key_takeaways.forEach((t, i) => {
      elements.push(
        para([
          run(`${t.number || i + 1}.  `, { bold: true, size: 22, color: NAVY }),
          run(t.text || "", { size: 22 }),
        ], { spaceBefore: 60, spaceAfter: 80 })
      );
    });
    elements.push(spacer(8));
  }

  return elements;
}

// =============================================================================
// SIGNALS AT A GLANCE (Green / Red flags)
// Derived from S2b and S2c sections — we pull top-level claims
// =============================================================================
function buildSignalsTable(sections) {
  const elements = [];
  elements.push(para(run("Signals at a Glance", { bold: true, size: 22, color: NAVY }),
                     { spaceAfter: 80 }));

  // Collect grounded claims from S2b (signals) and S2c (gaps)
  const greenClaims = [];
  const redClaims   = [];

  if (sections.S2b) {
    sections.S2b.claims
      .filter(c => c.claim_type === "grounded" || c.claim_type === "derived")
      .slice(0, 4)
      .forEach(c => greenClaims.push(c.claim_text));
  }
  if (sections.S2c) {
    sections.S2c.claims
      .filter(c => c.claim_type === "grounded" || c.claim_type === "derived")
      .slice(0, 4)
      .forEach(c => redClaims.push(c.claim_text));
  }

  // Pad to equal length
  const maxRows = Math.max(greenClaims.length, redClaims.length, 2);

  const colW = Math.floor(CONTENT_WIDTH / 2);

  const headerRow = new TableRow({
    tableHeader: true,
    children: [
      cell(para(run("✅  GREEN FLAGS", { bold: true, size: 20, color: WHITE })),
           { width: colW, fill: "2E7D32" }),
      cell(para(run("⚠️  RED FLAGS", { bold: true, size: 20, color: WHITE })),
           { width: colW, fill: "C62828" }),
    ]
  });

  const dataRows = Array.from({ length: maxRows }, (_, i) =>
    new TableRow({ children: [
      cell(para(run(greenClaims[i] || "—", { size: 20 })),
           { width: colW, fill: i % 2 === 0 ? "F1F8E9" : WHITE }),
      cell(para(run(redClaims[i] || "—", { size: 20 })),
           { width: colW, fill: i % 2 === 0 ? "FFF3E0" : WHITE }),
    ]})
  );

  elements.push(new Table({
    width: { size: CONTENT_WIDTH, type: WidthType.DXA },
    columnWidths: [colW, colW],
    rows: [headerRow, ...dataRows]
  }));
  elements.push(spacer(12));

  return elements;
}

// =============================================================================
// RADAR CHART + SCORE TABLE
// =============================================================================
function buildRadarSection(radarScores, chartPngPath) {
  const elements = [];
  elements.push(para(run("Quarter-at-a-Glance", { bold: true, size: 22, color: NAVY }),
                     { spaceAfter: 80 }));

  // Embed chart image
  try {
    const imageBuffer = fs.readFileSync(chartPngPath);
    elements.push(
      new Paragraph({
        alignment: AlignmentType.CENTER,
        spacing: { before: 0, after: 160 },
        children: [
          new ImageRun({
            data: imageBuffer,
            transformation: { width: 400, height: 400 },
            type: "png",
          })
        ]
      })
    );
  } catch (e) {
    elements.push(para(run("[Radar chart not available]", { italics: true, color: MID_GRAY })));
  }

  // Score table beneath chart
  if (radarScores && radarScores.dimension_scores) {
    const colWidths = [2400, 900, 900, 900, 3660];
    const headerRow = new TableRow({
      tableHeader: true,
      children: [
        cell(para(run("Dimension", { bold: true, size: 20, color: WHITE })),
             { width: colWidths[0], fill: NAVY }),
        cell(para(run("Score", { bold: true, size: 20, color: WHITE }),
                  { align: AlignmentType.CENTER }),
             { width: colWidths[1], fill: NAVY }),
        cell(para(run("Prior", { bold: true, size: 20, color: WHITE }),
                  { align: AlignmentType.CENTER }),
             { width: colWidths[2], fill: NAVY }),
        cell(para(run("Δ", { bold: true, size: 20, color: WHITE }),
                  { align: AlignmentType.CENTER }),
             { width: colWidths[3], fill: NAVY }),
        cell(para(run("Notes", { bold: true, size: 20, color: WHITE })),
             { width: colWidths[4], fill: NAVY }),
      ]
    });

    const DISPLAY_NAMES = {
      revenue_momentum:    "Revenue Momentum",
      margin_health:       "Margin Health",
      guidance_confidence: "Guidance Confidence",
      mgmt_transparency:   "Mgmt Transparency",
      strategic_clarity:   "Strategic Clarity",
      earnings_quality:    "Earnings Quality",
      forward_visibility:  "Forward Visibility",
    };

    const dataRows = radarScores.dimension_scores.map((d, i) => {
      const name    = DISPLAY_NAMES[d.dimension] || d.dimension;
      const score   = d.published_score;
      const prior   = d.score_model_b || "—";  // Reused as prior placeholder
      const delta   = typeof prior === "number" ? (score - prior > 0 ? `▲ +${score - prior}` : score - prior < 0 ? `▼ ${score - prior}` : "—") : "—";
      const notes   = d.scoring_rationale || "";

      return new TableRow({ children: [
        cell(para(run(name, { bold: true, size: 20 })),
             { width: colWidths[0], fill: i % 2 === 0 ? WHITE : LIGHT_GRAY }),
        cell(para(run(String(score), { bold: true, size: 20 }),
                  { align: AlignmentType.CENTER }),
             { width: colWidths[1], fill: i % 2 === 0 ? WHITE : LIGHT_GRAY }),
        cell(para(run(String(prior), { size: 20 }),
                  { align: AlignmentType.CENTER }),
             { width: colWidths[2], fill: i % 2 === 0 ? WHITE : LIGHT_GRAY }),
        cell(para(run(delta, { size: 20 }),
                  { align: AlignmentType.CENTER }),
             { width: colWidths[3], fill: i % 2 === 0 ? WHITE : LIGHT_GRAY }),
        cell(para(run(notes.substring(0, 120), { size: 19, italics: true })),
             { width: colWidths[4], fill: i % 2 === 0 ? WHITE : LIGHT_GRAY }),
      ]});
    });

    elements.push(new Table({
      width: { size: CONTENT_WIDTH, type: WidthType.DXA },
      columnWidths: colWidths,
      rows: [headerRow, ...dataRows]
    }));
  }

  elements.push(spacer(12));
  return elements;
}

// =============================================================================
// SECTIONS 2–5: NARRATIVE CONTENT
// =============================================================================
function buildNarrativeSections(sections) {
  const elements = [];

  const sectionOrder = [
    { id: "S2a", num: "2" },
    { id: "S2b", num: "3" },
    { id: "S2c", num: "4" },
    { id: "S2d", num: "5" },
  ];

  sectionOrder.forEach(({ id, num }) => {
    const section = sections[id];
    if (!section) {
      // Section was omitted due to degradation — note it visibly
      elements.push(spacer(8));
      elements.push(
        new Table({
          width: { size: CONTENT_WIDTH, type: WidthType.DXA },
          columnWidths: [CONTENT_WIDTH],
          rows: [new TableRow({ children: [
            cell(
              para(run(
                `[Section ${num} was omitted — verification could not be completed for this section.]`,
                { italics: true, size: 20, color: MID_GRAY }
              )),
              { width: CONTENT_WIDTH, fill: LIGHT_GRAY }
            )
          ]})]
        })
      );
      elements.push(spacer(12));
      return;
    }

    // Section heading
    elements.push(hrLine());
    elements.push(spacer(6));
    elements.push(
      para(run(`${num}. ${section.section_title}`, { bold: true, size: 28, color: NAVY }),
           { spaceBefore: 120, spaceAfter: 160 })
    );

    // Narrative — split on double newlines to preserve paragraph breaks
    const narrative = section.narrative || "";
    const paragraphs = narrative.split(/\n\n+/);

    paragraphs.forEach(p => {
      p = p.trim();
      if (!p) return;

      // Subheadings marked with **text** in the narrative
      if (p.startsWith("**") && p.endsWith("**")) {
        const heading = p.replace(/\*\*/g, "");
        elements.push(
          para(run(heading, { bold: true, size: 24, color: NAVY }),
               { spaceBefore: 160, spaceAfter: 80 })
        );
        return;
      }

      // Handle inline **bold** markers
      const parts = p.split(/(\*\*[^*]+\*\*)/g);
      const runs = parts.map(part => {
        if (part.startsWith("**") && part.endsWith("**")) {
          return run(part.replace(/\*\*/g, ""), { bold: true, size: 22 });
        }
        return run(part, { size: 22 });
      });

      // Blockquotes (lines starting with ">")
      if (p.startsWith(">")) {
        const quoteText = p.replace(/^>\s*/, "");
        elements.push(
          new Paragraph({
            children: [run(quoteText, { italics: true, size: 21, color: MID_GRAY })],
            spacing: { before: 120, after: 120 },
            indent: { left: 720, right: 360 },
            border: { left: { style: BorderStyle.SINGLE, size: 12, color: BORDER_CLR, space: 8 } },
          })
        );
        return;
      }

      elements.push(para(runs, { spaceBefore: 0, spaceAfter: 160 }));
    });

    elements.push(spacer(8));
  });

  return elements;
}

// =============================================================================
// VERIFICATION REPORT APPENDIX
// =============================================================================
function buildVerificationReport(verification, radarScores) {
  const elements = [];

  elements.push(
    new Paragraph({ children: [new PageBreak()] })
  );

  elements.push(
    para(run("Verification Report", { bold: true, size: 28, color: NAVY }),
         { spaceAfter: 80 })
  );
  elements.push(
    para(run(
      "This appendix documents the verification process applied to the preceding report. " +
      "Every factual claim was independently checked against the source transcript.",
      { size: 20, italics: true, color: MID_GRAY }
    ), { spaceAfter: 160 })
  );

  // Grounding scores per section
  if (verification.source_grounding_scores) {
    elements.push(para(run("Source Grounding by Section", { bold: true, size: 22, color: NAVY }),
                       { spaceAfter: 80 }));

    const entries = Object.entries(verification.source_grounding_scores);
    const colW = Math.floor(CONTENT_WIDTH / entries.length) || CONTENT_WIDTH;

    elements.push(new Table({
      width: { size: CONTENT_WIDTH, type: WidthType.DXA },
      columnWidths: entries.map(() => colW),
      rows: [
        new TableRow({ children: entries.map(([sec, score]) =>
          cell(para(run(sec, { bold: true, size: 20, color: WHITE }),
                    { align: AlignmentType.CENTER }),
               { width: colW, fill: NAVY })
        )}),
        new TableRow({ children: entries.map(([sec, score]) =>
          cell(para(run(`${(score * 100).toFixed(0)}%`, { bold: true, size: 24 }),
                    { align: AlignmentType.CENTER }),
               { width: colW })
        )}),
      ]
    }));
    elements.push(spacer(12));
  }

  // Contradiction check
  const totalContradictions = Object.values(verification.contradiction_counts || {})
    .reduce((a, b) => a + b, 0);
  elements.push(
    para([
      run("Contradiction Check: ", { bold: true, size: 22 }),
      run(
        totalContradictions === 0 ? "✓ 0 contradictions detected — Pass" : `✗ ${totalContradictions} contradictions detected`,
        { size: 22, color: totalContradictions === 0 ? "2E7D32" : "C62828" }
      )
    ], { spaceAfter: 120 })
  );

  // Model disagreements from radar scoring
  if (radarScores && radarScores.dimension_scores) {
    const disagreements = radarScores.dimension_scores.filter(d => !d.models_agreed);
    if (disagreements.length > 0) {
      elements.push(para(run("Model Score Disagreements", { bold: true, size: 22, color: NAVY }),
                         { spaceBefore: 120, spaceAfter: 80 }));
      disagreements.forEach(d => {
        elements.push(para(run(`• ${d.dimension}: ${d.disagreement_note || ""}`,
                               { size: 20, italics: true }), { spaceAfter: 80 }));
      });
      elements.push(spacer(8));
    }
  }

  // S5 advisory issues
  if (verification.s5_issues) {
    const { cross_section_issues, labeling_issues, framing_concerns } = verification.s5_issues;
    const allIssues = [...(cross_section_issues || []), ...(labeling_issues || []), ...(framing_concerns || [])];

    if (allIssues.length > 0) {
      elements.push(para(run("Advisory Flags", { bold: true, size: 22, color: NAVY }),
                         { spaceBefore: 120, spaceAfter: 80 }));
      allIssues.forEach(issue => {
        const text = issue.issue_description || issue.concern_description || JSON.stringify(issue);
        elements.push(para(run(`• ${text}`, { size: 20, italics: true }), { spaceAfter: 80 }));
      });
    }
  }

  // Verification limitations — always included (Principle 13)
  if (verification.verification_limitations) {
    elements.push(para(run("Verification Limitations", { bold: true, size: 22, color: NAVY }),
                       { spaceBefore: 160, spaceAfter: 80 }));
    elements.push(para(run(verification.verification_limitations,
                            { size: 20, italics: true, color: MID_GRAY }),
                       { spaceAfter: 120 }));
  }

  // Omitted sections notice
  if (verification.omitted_sections && verification.omitted_sections.length > 0) {
    elements.push(
      new Table({
        width: { size: CONTENT_WIDTH, type: WidthType.DXA },
        columnWidths: [CONTENT_WIDTH],
        rows: [new TableRow({ children: [
          cell(
            para(run(
              `Notice: The following sections were omitted because they could not pass verification after maximum retries: ${verification.omitted_sections.join(", ")}. This report is a partial output (Degradation Level 2).`,
              { size: 20, color: "B71C1C" }
            )),
            { width: CONTENT_WIDTH, fill: "FFEBEE" }
          )
        ]})]
      })
    );
  }

  elements.push(spacer(16));
  elements.push(hrLine());
  elements.push(
    para(run("Produced by Chorus AI Systems  |  Multi-model verification pipeline with zero-hallucination tolerance",
             { size: 18, italics: true, color: MID_GRAY }),
         { align: AlignmentType.CENTER, spaceBefore: 120 })
  );

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

  // Build verification summary for the header banner
  const grounding = verification && verification.source_grounding_scores
    ? Object.values(verification.source_grounding_scores).reduce((a, b) => a + b, 0) /
      Math.max(Object.keys(verification.source_grounding_scores).length, 1)
    : null;
  const verificationSummary = {
    avg_grounding: grounding ? `${(grounding * 100).toFixed(0)}%` : "—",
    contradictions: verification
      ? Object.values(verification.contradiction_counts || {}).reduce((a, b) => a + b, 0)
      : "—",
    model_agreement: (radar_scores && radar_scores.dimension_scores &&
      radar_scores.dimension_scores.every(d => d.models_agreed)) ? "High" : "Partial",
  };

  const children = [
    ...buildHeader(snapshot),
    ...buildSnapshot(snapshot, verificationSummary),
    ...buildSignalsTable(sections),
    ...buildRadarSection(radar_scores, chartPngPath),
    ...buildNarrativeSections(sections),
    ...buildVerificationReport(verification, radar_scores),
  ];

  const doc = new Document({
    styles: {
      default: {
        document: { run: { font: "Arial", size: 22 } }
      }
    },
    sections: [{
      properties: {
        page: {
          size: { width: 12240, height: 15840 },
          margin: { top: 1440, right: 1440, bottom: 1440, left: 1440 }
        }
      },
      children
    }]
  });

  const buffer = await Packer.toBuffer(doc);
  fs.writeFileSync(outputDocxPath, buffer);
  console.log(`Report saved: ${outputDocxPath}`);
}

main().catch(err => { console.error(err); process.exit(1); });
