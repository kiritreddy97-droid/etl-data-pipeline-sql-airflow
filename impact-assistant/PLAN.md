# IMPACT Help Desk: AI Assistant Plan

**Purpose:** Give CYFD staff real-time, role-specific "how do I do this in IMPACT?" answers that link to the RedMane guides and videos, so ongoing training does not depend only on live trainers.
**Status:** Draft for discussion. Costs and timelines are planning estimates to be validated with CYFD IT, procurement and security.

---

## 1. The problem

- RedMane built the curriculum and is rolling out initial training. There is no funded plan for ongoing, role-specific training after the contract.
- New hires, role changes, system releases and "I forgot how" moments continue indefinitely.
- Leadership is asking about funded in-house trainer positions. This plan tests an alternative or complement.

## 2. The idea in one sentence

A service-desk-style assistant that answers task questions in plain language, shows the steps, and links to the exact RedMane guide or video, using only approved content.

## 3. Recommendation: assistant plus a small trainer team

An assistant handles the high-volume, repeatable "how do I" questions. It does not replace people for:
- Policy and practice judgment ("should I?" versus "how do I?")
- New-hire onboarding cohorts and role transitions
- Change management when IMPACT releases new features
- Owning and improving the content the assistant depends on

**Ask for 2 to 3 positions, not a full trainer bench:**
1. Training lead / content owner (owns the knowledge base, reviews answers, owns the roadmap)
2. IMPACT trainer / floor support (live sessions, onboarding, office hours)
3. Optional: Instructional designer (turns gaps into new guides and videos)

The assistant's Insights view gives leadership evidence for staffing: which topics drive questions, which have no resource, and how many questions were deflected from live support.

## 4. How it works (retrieval, not "free chat")

```
Staff question
   -> role-aware search over approved content
   -> top matching guide/video passages
   -> AI writes a short answer using ONLY those passages
   -> answer + steps + source cards (guide, video, page, date)
   -> low confidence? say so and route to the help desk
```

Key design rules:
- **Grounded answers only.** If no approved source supports an answer, the assistant says so. It never guesses.
- **Always cite.** Every answer shows the source guide or video and its updated date.
- **Role-aware.** Role selection (or sign-in group) filters content and phrasing.
- **No client data.** The assistant never connects to IMPACT records. Users are told not to type names or case numbers, and inputs are screened for obvious identifiers.
- **Easy human handoff.** "Ask a person" sends the question and conversation to the help desk queue.

## 5. Architecture options

| Option | What it is | Pros | Cons | Fit |
|---|---|---|---|---|
| **A. Microsoft Copilot Studio / Azure OpenAI** | Low-code bot grounded on SharePoint or uploaded files, inside the State's M365/Azure tenant | Likely already in state agreements, SSO, government cloud options, fastest to pilot | Less control over retrieval tuning | **Best first pilot** if CYFD has M365/Azure |
| **B. Custom build on a cloud AI service** (Azure OpenAI, AWS Bedrock, or Anthropic API via a government-approved cloud) | Our own web app, vector search over content, model API | Full control of UX, analytics, guardrails | Needs developers and ongoing maintenance | Phase 2 if Option A hits limits |
| **C. Vendor chatbot product** | Off-the-shelf knowledge-base bot | Quick setup | Recurring license, data residency questions, less flexibility | Compare in procurement |
| **D. Ask RedMane** | Add an assistant to the IMPACT contract | Closest to the system and content | Vendor lock-in, cost, timing | **Ask anyway**: could be a change order or an in-product help widget |

The front-end prototype in this folder is vendor-neutral. It could sit in front of A, B or C.

## 6. Content is the real work

The assistant is only as good as its knowledge base.

1. **Inventory** all RedMane artifacts: guides, quick references, videos, release notes, FAQs. Record owner, role, topic, and last-updated date.
2. **Confirm rights.** Check the RedMane contract for permission to ingest and index their materials, and for who owns updates.
3. **Prepare video content.** Videos need transcripts or captions to be searchable. Link to the timestamp where possible.
4. **Tag** each item by role, workflow (intake, investigation, placement, court, etc.) and IMPACT release version.
5. **Retire stale content.** Every item gets a review date. Out-of-date answers are worse than no answer.
6. **Change process.** When IMPACT releases an update, the content owner updates the knowledge base the same sprint.

## 7. Security, privacy and compliance (decide early)

- Child welfare data is highly sensitive. Design so the assistant **never touches case data**.
- Hosting inside the State's tenant, with SSO and audit logging.
- Confirm that vendor models do not train on CYFD inputs, and where data is stored.
- Review with CYFD IT security, the privacy officer and legal. Check State AI policy and any required procurement or ITSD review.
- Retention policy for conversation logs (needed for improvement, but may contain stray identifiers).
- Accessibility: WCAG 2.1 AA, keyboard and screen-reader support.
- Plain notice to staff: what the assistant is, what it is not, and that answers are not policy guidance.

## 8. Phased roadmap

| Phase | Weeks | Outcome |
|---|---|---|
| **0. Discovery** | 1-4 | Content inventory, RedMane rights, top-50 questions from the help desk/trainers, security pre-review, success metrics agreed |
| **1. Pilot** | 5-12 | Assistant covering 2 roles and ~10 workflows (e.g. caseworkers and supervisors); 50-100 pilot users; weekly review of unanswered questions |
| **2. Evaluate** | 13-16 | Compare pilot to baseline: deflection, helpfulness, accuracy audit by SMEs, user feedback; go/no-go and staffing recommendation to leadership |
| **3. Scale** | 17-30 | Add roles and workflows, SSO, help-desk integration, Insights dashboard, release-update process |
| **4. Sustain** | ongoing | Quarterly content audit, monthly accuracy sampling, annual security review |

## 9. How we will know it works

| Metric | Target to agree on |
|---|---|
| Answer helpfulness (thumbs up) | Set after pilot baseline |
| Answer accuracy (SME audit of a random sample) | High threshold (e.g. 95%+ correct and sourced) before scaling |
| "No good answer" rate | Falling over time as content gaps are closed |
| Help-desk/trainer tickets for how-to questions | Reduction versus pre-pilot baseline |
| Time to answer | Seconds, versus hours for a ticket |
| Adoption by role | Share of active staff using it monthly |
| Staff confidence in IMPACT (short survey) | Improvement vs. baseline |

## 10. Rough cost shape (to validate)

- **Pilot on Option A:** mostly staff time (content prep, SME review) plus modest licensing and cloud usage. Lowest cost path.
- **Custom build (Option B):** typically 1 developer/analyst and part-time design for the build, then maintenance. Model usage costs scale with questions asked.
- **Content upkeep** is the recurring cost, and is the argument for keeping at least one content owner position.
- Compare against fully loaded cost of 2-3 trainer FTEs and the help-desk time absorbed today.

## 11. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Wrong or invented answers | Grounded-only answers, citations, confidence threshold, SME accuracy audits, easy "report a bad answer" |
| Stale content after IMPACT releases | Named content owner, release-linked update process, review dates |
| Staff enter client information | Banner, input screening, no connection to IMPACT data, retention limits |
| Low adoption | Embed link in IMPACT and intranet, supervisor champions, short launch demos |
| RedMane content rights or cooperation | Raise early; consider a contract amendment |
| Leadership reads it as "no trainers needed" | Position as a complement; use pilot data to size the team |
| Policy questions mistaken for how-to | Scope to system tasks; redirect policy questions to supervisors/policy staff |

## 12. Decisions and next steps

**Decisions needed from leadership/Pilar**
1. Is a pilot approved, and with which two roles?
2. Who is the executive sponsor, and who owns content long-term?
3. Do we approach RedMane first about rights, a change order, or an in-product help option?

**Next 30 days**
1. Pull the RedMane artifact list and contract language on materials.
2. Gather the top 50 how-to questions from help desk, trainers and supervisors.
3. Meet CYFD IT security/privacy and check which platforms (M365, Azure, others) are already approved.
4. Use the prototype in `index.html` in two or three staff listening sessions to test the experience.
5. Define pilot success metrics and baseline them now.

## 13. About the prototype

`index.html` is a working front end with **sample content only**. It demonstrates role selection, plain-language Q&A, step lists, guide and video source cards, helpful/not-helpful feedback, human escalation, the no-match behavior, and an Insights tab for training leads. Matching is simple keyword logic standing in for the real retrieval and AI layer.
