# IMPACT Help Desk Assistant
## Implementation Guide and Technical Requirements

**Audience:** CYFD leadership, IT/security, procurement, and the training team
**Status:** Draft for review. Items marked **[CONFIRM]** need a decision or verification with CYFD IT, security, legal or RedMane. Cost figures are not included because they depend on the platform chosen.
**Companion files:** `PLAN.md` (business case and roadmap), `impact-helpdesk-widget.js` (embeddable widget prototype), `IMPACT-Help-Widget-demo.html` (single-file demo).

---

## 1. What is being built

A help assistant that staff open from a small round button at the bottom-right of the screen. They type a how-to question, and it returns short steps plus links to the matching RedMane guide or video. It answers only from approved content, says so when it has no answer, and can hand the question to the help desk.

Five components:

| # | Component | Role |
|---|---|---|
| 1 | **Widget (front end)** | Floating icon and chat panel shown inside the host web page |
| 2 | **Assistant API** | Receives questions, calls search and the AI model, applies guardrails, returns structured answers |
| 3 | **Knowledge base** | Indexed RedMane guides, quick references, video transcripts and FAQs, with metadata |
| 4 | **AI model service** | Writes the answer from retrieved passages only |
| 5 | **Admin and analytics** | Content management, unanswered-question queue, usage and quality reporting |

## 2. Where the button can live (deployment options)

IMPACT is a vendor-built system, so whether a script can be added to IMPACT pages is the first question to settle.

| Option | How it works | Needs | Effort |
|---|---|---|---|
| **A. Embed in IMPACT itself** | RedMane adds the one-line script (or a Help link) to the IMPACT page template | RedMane agreement and change order, CSP allowance for the widget host **[CONFIRM]** | Lowest for staff, depends on RedMane |
| **B. CYFD intranet / SharePoint** | Widget embedded in the intranet home or a "Training" page | CYFD web admin access | Low |
| **C. Browser extension or managed bookmark** | CYFD IT pushes a small extension or toolbar link that shows the button on IMPACT's domain | IT endpoint management (Intune, Group Policy) **[CONFIRM]** | Medium; works without changing IMPACT |
| **D. Microsoft Teams app / tab** | Same assistant as a Teams app | Teams admin, bot registration | Medium |
| **E. Standalone page** | Hosted page opened in a second tab or window | Hosting and URL | Lowest, but less convenient |

**Recommendation:** Start with **E plus B** for the pilot (no vendor change needed), pursue **A** with RedMane in parallel, and evaluate **C** if A is not possible.

### Embedding the widget
```html
<script>
  window.ImpactHelpDeskConfig = {
    title: "IMPACT Help",
    endpoint: "https://helpdesk.example.gov/api/ask",
    escalateUrl: "https://helpdesk.example.gov/api/escalate"
  };
</script>
<script src="https://helpdesk.example.gov/widget.js" defer></script>
```
- The widget uses a Shadow DOM, so host-page styles cannot break it and it cannot break the host page.
- No frameworks or libraries are required. The prototype is about 19 KB.
- The host page's Content Security Policy must allow the widget script and API origin (`script-src`, `connect-src`). If the widget is loaded in an iframe instead, allow it with `frame-src` / `frame-ancestors`.

## 3. Reference architecture

```
Staff browser
  └─ Widget (JS)  ──HTTPS──▶  API gateway / WAF
                                   │
                                   ▼
                          Assistant API (stateless)
                           ├─ Auth: validate SSO token, read role
                           ├─ Input checks: length, PII patterns, abuse/rate limit
                           ├─ Retrieval ──▶ Search index (hybrid keyword + vector)
                           │                    ▲
                           │            Ingestion pipeline ◀── RedMane content,
                           │            (parse, chunk, embed)   transcripts, FAQs
                           ├─ Model call ──▶ AI model service (grounded prompt)
                           ├─ Output checks: citation present, confidence threshold
                           └─ Log (no PII) ──▶ Analytics store
                                   │
                  Escalation ──▶ Help desk system (ticket with transcript)
Admin portal ──▶ content review, gaps queue, dashboards
```

### Answer rules enforced in code
1. Retrieve the top passages for the question, filtered by the user's role and the current IMPACT release.
2. The model is instructed to answer **only** from those passages and to return "no answer" if they do not cover it.
3. Every answer must include at least one source (title, type, date, link). Answers without a source are blocked.
4. Below a confidence threshold, show "I could not find an approved answer" and offer escalation.
5. Policy or case-judgment questions are detected and redirected to the supervisor or policy staff.

### API contract (used by the widget)
**POST `/api/ask`**
```json
{ "question": "How do I add a case note?", "role": "caseworker", "sessionId": "abc123" }
```
Response:
```json
{
  "found": true,
  "confidence": 0.92,
  "summary": "Here is how to add a case note or contact.",
  "steps": ["Open the case and go to Contacts.", "..."],
  "sources": [
    { "type": "guide", "title": "Documenting Contacts and Case Notes", "meta": "7 pages · updated Sep 2026", "url": "https://..." },
    { "type": "video", "title": "Entering a contact note", "meta": "4 min", "url": "https://...#t=95" }
  ]
}
```
**POST `/api/ask/feedback`** `{ sessionId, question, helpful }` · **POST `/api/escalate`** `{ sessionId, question }`

## 4. Technical requirements

### 4.1 Platform and hosting
- Cloud environment approved for State data: Azure Government, AWS GovCloud, or the State's approved tenant **[CONFIRM]**
- Separate dev, test and production environments
- Infrastructure defined as code; CI/CD pipeline with automated tests
- Managed services preferred (app hosting, managed search, managed database) to keep operations small
- TLS 1.2+ everywhere, WAF in front of the API, API rate limiting

### 4.2 Identity and access
- Single sign-on with the State identity provider (e.g. Entra ID / SAML / OIDC) **[CONFIRM]**
- Role taken from the identity group where possible, with the widget's role selector as a fallback for the demo
- Admin roles separate from user roles; least privilege and MFA for admins
- Restrict access to CYFD staff and approved partners (network or identity based)

### 4.3 Content and search
- Source types: PDF, Word, slides, HTML, FAQs, release notes, video transcripts or captions
- Ingestion pipeline: extract text, chunk, attach metadata (role, workflow, IMPACT release, owner, review date), create embeddings, index
- Hybrid search (keyword plus vector) with metadata filters
- Videos: captions or transcripts required; store timestamps so answers deep-link into the video
- Content versioning and retirement; automatic flag when a review date passes
- **Rights check:** confirm the RedMane contract allows indexing and reuse of the materials **[CONFIRM]**

### 4.4 AI model service
- Model hosted in an environment the State approves, with a contract term that CYFD inputs are **not used for model training** **[CONFIRM]**
- Data residency in the United States
- Grounded-answer prompt, low temperature, structured JSON output
- Content-safety filters and a fallback if the model service is down (show guides search instead)
- Token and cost monitoring with budget alerts

### 4.5 Security and privacy
- **No connection to IMPACT case records.** The assistant has no read or write path to client data.
- Input screening for obvious identifiers (names with case numbers, SSNs, dates of birth) with a warning and redaction before logging
- Conversation logs retained for a defined period (e.g. 90 to 180 days **[CONFIRM]**), encrypted at rest, access restricted
- Audit logging of admin actions and content changes
- Security review before pilot: threat model, penetration test, privacy impact assessment, review against State AI and IT policy **[CONFIRM]**
- Compliance mapping with the CYFD privacy officer and legal (child welfare confidentiality requirements) **[CONFIRM]**
- Prompt-injection defenses: retrieved content is treated as data, not instructions

### 4.6 Accessibility and usability
- WCAG 2.1 AA, keyboard operable, screen reader labels, visible focus, reduced-motion support (the prototype already includes these basics)
- Works on supported browsers at CYFD (Edge, Chrome) and on tablets; full-screen layout on phones
- Plain-language answers, reading level appropriate for the workforce

### 4.7 Non-functional targets (propose, then agree)
| Area | Target |
|---|---|
| Response time | Answer in under 5 seconds for 95% of questions |
| Availability | 99.5% during business hours; graceful fallback if AI is unavailable |
| Concurrency | Sized for the whole workforce, with peak load after trainings and releases |
| Scalability | Stateless API, autoscaling |
| Observability | Request tracing, error alerts, quality dashboards |
| Backup / recovery | Defined RPO and RTO for the index, content store and logs |

### 4.8 Analytics and quality
- Capture (without PII): topic, role, match confidence, helpful or not, escalated or not, content gaps
- Insights view for the training lead: top topics, unanswered questions, resources with low helpfulness
- Monthly accuracy audit: SMEs score a random sample of answers for correctness and source match

### 4.9 Integrations
| System | Purpose | Required? |
|---|---|---|
| SSO / identity provider | Sign-in and role | Yes |
| Help desk / ticketing | "Ask a person" with transcript | Yes |
| RedMane resource library | Source content, links, update feed | Yes |
| IMPACT release notes | Trigger content updates | Recommended |
| Teams / email | Notifications to content owner | Optional |

## 5. People and roles

| Role | Responsibility | Time |
|---|---|---|
| Executive sponsor | Decisions, funding, removes blockers | Part-time |
| Product / training lead (content owner) | Priorities, content quality, release updates, accuracy audits | **Full-time (recommended position)** |
| Solution architect / developer(s) | Build and maintain API, ingestion, widget | Part-time to full-time during build |
| IT security / privacy officer | Reviews, approvals, ongoing oversight | As needed |
| Subject matter experts (trainers, supervisors) | Validate answers, supply top questions | A few hours per month each |
| Help desk lead | Escalation process | Part-time |
| RedMane contact | Content access, change requests, embedding | As needed |
| Instructional designer | New guides and videos for gaps | Optional position |

## 6. Implementation steps

**Phase 0: Discovery (weeks 1-4)**
1. Confirm content rights and obtain the RedMane artifact inventory.
2. Collect the top 50 how-to questions from help desk, trainers and supervisors.
3. Decide the platform (Copilot Studio / Azure, custom build, or vendor product).
4. Hold the security and privacy pre-review; identify required approvals.
5. Agree pilot scope (two roles, about ten workflows) and success metrics; capture a baseline.

**Phase 1: Pilot build (weeks 5-12)**
1. Stand up the dev environment, SSO and the ingestion pipeline.
2. Ingest and tag pilot content; create transcripts for videos.
3. Build the assistant API with grounding and guardrails; connect the widget (replace the sample data).
4. Connect the help desk escalation.
5. SME test with a golden set of 50 to 100 questions; fix content gaps.
6. Security testing; go-live checklist; staff notice and short training.
7. Launch to 50 to 100 pilot users through option E and B.

**Phase 2: Evaluate (weeks 13-16)**
1. Compare to baseline on the metrics below.
2. Run the accuracy audit and a user survey.
3. Go/no-go and staffing recommendation to leadership.

**Phase 3: Scale (weeks 17-30)**
1. Add roles and workflows; pursue embedding in IMPACT (option A or C).
2. Admin portal and dashboards; release-update process with RedMane.
3. Operational runbook, on-call, and support model.

**Phase 4: Sustain**
- Quarterly content audit, monthly accuracy sampling, annual security review.

## 7. Testing and quality assurance
- **Golden question set:** 100+ real questions with approved answers; run on every content or model change
- **Accuracy gate:** SME-scored sample must meet the agreed threshold before each rollout stage
- **Negative tests:** policy questions, off-topic questions, attempts to extract client information, prompt-injection attempts, questions with no content
- **Accessibility test:** automated scan plus manual screen reader and keyboard testing
- **Load test** at expected peak; **failover test** with the AI service disabled
- **User acceptance** with pilot staff, including a supervisor group

## 8. Operations and support
- Named owners for content, platform and incidents
- Release process: when IMPACT changes, the content owner updates the knowledge base in the same sprint
- Monitoring alerts for errors, latency, model cost and a rise in unanswered questions
- Incident process for incorrect or harmful answers: disable the topic, correct the content, notify staff
- Monthly report to the sponsor: usage, quality, gaps, escalations

## 9. Risks and open decisions

| Risk | Mitigation |
|---|---|
| Wrong or invented answers | Grounded-only answers, required citations, confidence threshold, accuracy audits |
| Stale content after IMPACT releases | Content owner, review dates, release-linked updates |
| Client information typed into the chat | Banner, input screening, redaction, no IMPACT data access, retention limits |
| Cannot embed in IMPACT | Use intranet, extension or Teams options |
| RedMane rights or cooperation | Raise at the start; consider a contract amendment |
| Low adoption | Supervisor champions, links in IMPACT and intranet, short launch demos |
| Read as "no trainers needed" | Position as a complement; use pilot data to size the team |

**Decisions needed**
1. Platform choice and approved cloud environment
2. Whether RedMane will add the widget or a help link to IMPACT
3. Content ownership and the funded content-owner position
4. Log retention period and privacy sign-off
5. Pilot roles, user group and success thresholds

## 10. Checklist for the first meeting with IT security
- [ ] Which cloud and AI services are already approved for State data?
- [ ] Is there a State AI policy or approval process we must follow?
- [ ] Which identity provider and groups can supply roles?
- [ ] Can a script or a link be added to IMPACT, the intranet or both?
- [ ] What are the log retention and incident reporting rules?
- [ ] Who signs off on the privacy impact assessment?

## 11. What the current prototype does and does not do

| Included | Not yet included |
|---|---|
| Floating help button and chat panel that embeds with one script tag | Real search or AI model (uses sample keyword matching) |
| Role selection, steps, guide and video source cards | Real RedMane content and links |
| Helpful / not helpful, "Ask a person", no-match behavior | SSO, logging, help desk integration |
| Accessibility basics, dark mode, mobile layout | Admin portal and analytics backend |
| API contract defined so the front end can connect to a real service | Production security controls |
